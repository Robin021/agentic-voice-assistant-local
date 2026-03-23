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

import { GatewayVpcEndpointAwsService, IpAddresses, IVpc, SubnetType, Vpc } from 'aws-cdk-lib/aws-ec2';
import { Construct } from 'constructs';
import { SystemConfig } from '../configs/systemConfig';

export interface VPCConstructProps {
  readonly config: SystemConfig;
}

export class VPCConstruct extends Construct {
  readonly vpc: IVpc;

  constructor(scope: Construct, id: string, props: VPCConstructProps) {
    super(scope, id);

    if (props.config.network.vpcId) {
      this.vpc = Vpc.fromLookup(this, 'ImportedVPC', {
        vpcId: props.config.network.vpcId,
      });
    } else {
      this.vpc = new Vpc(this, 'NewVPC', {
        ipAddresses: IpAddresses.cidr('10.0.0.0/16'),
        enableDnsHostnames: true,
        enableDnsSupport: true,
        subnetConfiguration: [
          {
            name: 'public',
            subnetType: SubnetType.PUBLIC,
            cidrMask: 24,
          },
          {
            name: 'private',
            subnetType: SubnetType.PRIVATE_WITH_EGRESS,
            cidrMask: 24,
          },
          {
            name: 'isolated',
            subnetType: SubnetType.PRIVATE_ISOLATED,
            cidrMask: 24,
          },
        ],
        maxAzs: 3,
        natGateways: 1,
      });
      this.vpc.addGatewayEndpoint(id + 'S3Endpoint', {
        service: GatewayVpcEndpointAwsService.S3,
      });
      this.vpc.addGatewayEndpoint(id + 'DynamoDBEndpoint', {
        service: GatewayVpcEndpointAwsService.DYNAMODB,
      });
    };
  }
}


