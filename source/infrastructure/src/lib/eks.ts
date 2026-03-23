/**
 *  Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 *
 *  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
 *  with the License. A copy of the License is located at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  or in the 'license' file accompanying this file. This file is distributed on an 'AS IS' BASIS, WITHOUT WARRANTIES
 *  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions
 *  and limitations under the License.
 */
import { KubectlV33Layer } from '@aws-cdk/lambda-layer-kubectl-v33/lib/index';
import { Aws, CfnOutput } from 'aws-cdk-lib';
import { IVpc, SubnetType, SecurityGroup, Port, Subnet, InstanceType, Peer } from 'aws-cdk-lib/aws-ec2';
import { AccessScopeType, Cluster, KubernetesVersion, EndpointAccess, AuthenticationMode, AccessPolicy, AccessPolicyArn } from 'aws-cdk-lib/aws-eks';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import { SystemConfig } from '../configs/systemConfig';


export interface EKSConstructProps {
  readonly vpc: IVpc;
  readonly config: SystemConfig;
}

export class EKSConstruct extends Construct {
  readonly cluster: Cluster;
  readonly helmDeployRole: iam.Role;

  constructor(scope: Construct, id: string, props: EKSConstructProps) {
    super(scope, id);

    // EKS Control Plane Security Group
    const eksControlPlaneSecurityGroup = new SecurityGroup(this, 'EKSControlPlaneSG', {
      vpc: props.vpc,
      description: 'Cluster communication with worker nodes',
      allowAllOutbound: true,
    });
    eksControlPlaneSecurityGroup.addIngressRule(
      Peer.ipv4(props.vpc.vpcCidrBlock),
      Port.allTraffic(),
      'Allow all traffic from within the VPC.',
    );
    eksControlPlaneSecurityGroup.connections.allowFrom(
      eksControlPlaneSecurityGroup,
      Port.allTraffic(),
      'Allow all traffic within ALB security group',
    );

    const eksClusterRole = new iam.Role(this, 'EKSClusterRole', {
      assumedBy: new iam.ServicePrincipal('eks.amazonaws.com'),
      managedPolicies: [iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonEKSClusterPolicy')],
    });

    const eksSubnets = this.getClusterSubnets(props);
    const clusterName = props.config.cluster.clusterName || 'voice-assistant-cluster';
    this.cluster = new Cluster(this, 'EKSCluster', {
      version: KubernetesVersion.of(props.config.cluster.version),
      clusterName: clusterName,
      vpc: props.vpc,
      vpcSubnets: eksSubnets,
      securityGroup: eksControlPlaneSecurityGroup,
      role: eksClusterRole,
      endpointAccess: EndpointAccess.PRIVATE,
      defaultCapacity: 0,
      kubectlLayer: new KubectlV33Layer(this, 'KubectlLayer'),
      authenticationMode: AuthenticationMode.API_AND_CONFIG_MAP,
      outputConfigCommand: true,
    });

    // Enable EKS Pod Identity Agent
    this.cluster.eksPodIdentityAgent;
    this.createNodeGroup(props);
    this.createAccessEntry();

    this.helmDeployRole = this.createHelmRole();
  }

  private createHelmRole() {
    // Create a new IAM role for Helm chart deployment
    const role = new iam.Role(this, 'HelmDeployRole', {
      assumedBy: new iam.ServicePrincipal('eks.amazonaws.com'),
    });

    // Add a condition to the trust relationship
    role.assumeRolePolicy?.addStatements(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        principals: [new iam.ServicePrincipal('eks.amazonaws.com')],
        actions: ['sts:AssumeRole'],
        conditions: {
          ArnLike: {
            'aws:SourceArn': this.cluster.clusterArn,
          },
        },
      }),
    );

    this.cluster.awsAuth.addRoleMapping(role, { groups: ['system:masters'] });

    return role;
  }

  private getClusterSubnets(props: EKSConstructProps) {
    if (props.config.cluster.vpcSubnetIds && props.config.cluster.vpcSubnetIds.length > 0) {
      const subnets = props.config.cluster.vpcSubnetIds.map(
        subnetId => Subnet.fromSubnetId(props.vpc, `VpcSubnet-${subnetId}`, subnetId),
      );

      console.log(`EKS: using subnets: ${subnets.map(s => s.subnetId).join(', ')}`);
      return [{ subnets }];
    }

    console.log('EKS: using default private subnets');
    return [{ subnetType: SubnetType.PRIVATE_WITH_EGRESS }];
  }

  private getNodeGroupSubnets(props: EKSConstructProps) {
    if (props.config.cluster.managedNodeGroups.gpu.workerNodeSubnetIds &&
      props.config.cluster.managedNodeGroups.gpu.workerNodeSubnetIds.length > 0) {
      const subnets = props.config.cluster.managedNodeGroups.gpu.workerNodeSubnetIds.map(
        subnetId => Subnet.fromSubnetId(props.vpc, `WorkerNodeSubnet-${subnetId}`, subnetId),
      );

      console.log(`GPU Worker Nodes: using subnets: ${subnets.map(s => s.subnetId).join(', ')}`);
      return { subnets };
    }

    console.log('GPU Worker Nodes: using default private subnets');
    return { subnetType: SubnetType.PRIVATE_WITH_EGRESS };
  }

  private createNodeGroup(props: EKSConstructProps) {
    // Create node group IAM role
    const pricinple = props.config.isChinaRegion ? 'ec2.amazonaws.com.cn' : 'ec2.amazonaws.com';
    const nodeGroupRole = new iam.Role(this, 'NodeGroupRole', {
      assumedBy: new iam.ServicePrincipal(pricinple),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonEKSWorkerNodePolicy'),
        iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonEKS_CNI_Policy'),
        iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonEC2ContainerRegistryReadOnly'),
        iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonS3FullAccess'),
        iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore'),
      ],
    });

    const invokeSagemakerPolicy = new iam.PolicyStatement({
      actions: ['sagemaker:InvokeEndpoint'],
      resources: ['*'],
    });

    nodeGroupRole.addToPolicy(invokeSagemakerPolicy);

    const nodeGroupSubnets = this.getNodeGroupSubnets(props);

    this.cluster.addNodegroupCapacity('GPUNodeGroup', {
      instanceTypes: [new InstanceType(props.config.cluster.managedNodeGroups.gpu.instanceType)],
      minSize: props.config.cluster.managedNodeGroups.gpu.minSize || 1,
      desiredSize: props.config.cluster.managedNodeGroups.gpu.desiredSize || 1,
      maxSize: props.config.cluster.managedNodeGroups.gpu.maxSize || 4,
      diskSize: props.config.cluster.managedNodeGroups.gpu.diskSize || 200,
      nodeRole: nodeGroupRole,
      subnets: nodeGroupSubnets,
      labels: {
        'nvidia.com/gpu.present': 'true',
        'nvidia.com/mps.capable': 'true',
      },
    });

    this.cluster.addNodegroupCapacity('CPUNodeGroup', {
      instanceTypes: [new InstanceType(props.config.cluster.managedNodeGroups.cpu.instanceType)],
      minSize: props.config.cluster.managedNodeGroups.cpu.minSize || 1,
      desiredSize: props.config.cluster.managedNodeGroups.cpu.desiredSize || 1,
      maxSize: props.config.cluster.managedNodeGroups.cpu.maxSize || 4,
      diskSize: props.config.cluster.managedNodeGroups.cpu.diskSize || 200,
      nodeRole: nodeGroupRole,
      subnets: nodeGroupSubnets,
      labels: {
        'app/voicebot': 'enabled',
        'app/stunner': 'enabled',
      },
    });
  }

  private createAccessEntry() {
    // Create a new access entry for the access role
    const accessEntryRole = new iam.Role(this, 'AccessEntryRole', {
      assumedBy: new iam.AccountRootPrincipal(),
    });

    // Use the grantAccess method for better readability
    this.cluster.grantAccess('ConfigAccessEntry', accessEntryRole.roleArn, [
      new AccessPolicy({
        accessScope: {
          type: AccessScopeType.CLUSTER,
        },
        policy: AccessPolicyArn.AMAZON_EKS_CLUSTER_ADMIN_POLICY,
      }),
    ]);

    const CfnConfigCommand = new CfnOutput(this, 'ConfigCommand', {
      value: `aws eks update-kubeconfig --name ${this.cluster.clusterName} --region ${Aws.REGION} --role-arn ${accessEntryRole.roleArn}`,
      description: 'Command to update kubeconfig',
    });
    CfnConfigCommand.overrideLogicalId('EKSConfigCommand');
  }
}