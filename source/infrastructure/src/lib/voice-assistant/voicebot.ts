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

import * as path from 'path';
import { Aws, Duration, CfnOutput, RemovalPolicy, SecretValue, aws_dynamodb as ddb } from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as eks from 'aws-cdk-lib/aws-eks';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3_assets from 'aws-cdk-lib/aws-s3-assets';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';
import * as yaml from 'js-yaml';
import { SystemConfig } from '../../configs/systemConfig';
import { loadYaml } from '../utils';

export interface VoicebotConstructProps {
  readonly config: SystemConfig;
  readonly vpc: ec2.IVpc;
  readonly cluster: eks.Cluster;
  readonly helmDeployRole: iam.Role;
}

export class VoicebotConstruct extends Construct {

  constructor(scope: Construct, id: string, props: VoicebotConstructProps) {
    super(scope, id);

    const secret = new secretsmanager.Secret(this, 'Secret', {
      description: 'Secret configuration for voicebot',
      secretStringValue: SecretValue.unsafePlainText(JSON.stringify({
        webrtc: {
          stunner_user: props.config.voiceAssistant.stunner.username,
          stunner_password: props.config.voiceAssistant.stunner.password,
        },
        model_list: [
          {
            model_name: 'basic-llm',
            litellm_params: props.config.voiceAssistant.litellmParams,
          },
          {
            model_name: 'context-relevance',
            litellm_params: {
              model: 'openai/Qwen/Qwen3-0.6B',
              api_base: `http://qwen3-0p6b.${props.config.voiceAssistant.namespace}.svc.cluster.local:${props.config.voiceAssistant.contextRelevance.port.toString()}/v1`,
              api_key: 'EMPTY',
              chat_template_kwargs: {
                enable_thinking: false,
              },
            },
          },
          {
            model_name: 'automatic-speech-recognition',
            litellm_params: {
              model: 'openai/sensevoice',
              api_base: `http://sensevoice.${props.config.voiceAssistant.namespace}.svc.cluster.local:${props.config.voiceAssistant.stt.port.toString()}/v1`,
              api_key: 'EMPTY',
            },
          },
          {
            model_name: 'text-to-speech',
            litellm_params: {
              model: 'funasr/cosyvoice',
              api_base: `http://cosyvoice.${props.config.voiceAssistant.namespace}.svc.cluster.local:${props.config.voiceAssistant.tts.port.toString()}/v1`,
              api_key: 'EMPTY',
            },
          },
        ],
      }),
      ),
    });

    let voicebotImage = props.config.voiceAssistant.voicebot.image;
    if (!voicebotImage) {
      const voicebotImageAsset = new ecr_assets.DockerImageAsset(this, 'VoicebotImageAsset', {
        directory: path.join(__dirname, '../../../../../docker/voicebot'),
      });
      voicebotImage = voicebotImageAsset.imageUri;
    };

    let stunnerdImage = props.config.voiceAssistant.stunner.dataplane.image;
    if (!stunnerdImage) {
      const stunnerdImageAsset = new ecr_assets.DockerImageAsset(this, 'StunnerdImageAsset', {
        directory: path.join(__dirname, '../../../../../docker/stunnerd'),
      });
      stunnerdImage = stunnerdImageAsset.imageUri;
    };

    let stunnerGatewayOperatorImage = props.config.voiceAssistant.stunner.gatewayOperator.image;
    if (!stunnerGatewayOperatorImage) {
      const stunnerGatewayOperatorImageAsset = new ecr_assets.DockerImageAsset(this, 'StunnerGatewayOperatorImageAsset', {
        directory: path.join(__dirname, '../../../../../docker/stunner-gateway-operator'),
      });
      stunnerGatewayOperatorImage = stunnerGatewayOperatorImageAsset.imageUri;
    };

    let stunnerAuthServerImage = props.config.voiceAssistant.stunner.authService.image;
    if (!stunnerAuthServerImage) {
      const stunnerAuthServerImageAsset = new ecr_assets.DockerImageAsset(this, 'StunnerAuthServerImageAsset', {
        directory: path.join(__dirname, '../../../../../docker/stunner-auth-server'),
      });
      stunnerAuthServerImage = stunnerAuthServerImageAsset.imageUri;
    };


    const serviceAccount = props.cluster.addServiceAccount('ServiceAccount', {
      name: 'voicebot',
      namespace: props.config.voiceAssistant.namespace,
    });
    secret.grantRead(serviceAccount);

    if (!props.config.isChinaRegion) {
      serviceAccount.addToPrincipalPolicy(new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock:InvokeModel',
          'bedrock:InvokeModelWithResponseStream',
        ],
        resources: [
          `arn:${Aws.PARTITION}:bedrock:*:${Aws.ACCOUNT_ID}:inference-profile/*`,
          `arn:${Aws.PARTITION}:bedrock:*::foundation-model/*`,
        ],
      }));
    }

    const metadataTable = new ddb.Table(this, 'Metadata', {
      partitionKey: {
        name: 'pk',
        type: ddb.AttributeType.STRING,
      },
      sortKey: {
        name: 'sk',
        type: ddb.AttributeType.STRING,
      },
      billingMode: ddb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: RemovalPolicy.DESTROY,
      encryption: ddb.TableEncryption.AWS_MANAGED,
    });
    (
      metadataTable.node.defaultChild as ddb.CfnTable
    ).overrideLogicalId('Metadata');
    metadataTable.grantReadWriteData(serviceAccount);

    // Application Load Balancer Security Group
    const albSecurityGroup = new ec2.SecurityGroup(this, 'ALBSG', {
      vpc: props.vpc,
      description: 'Security Group for ALB',
      allowAllOutbound: true,
    });
    albSecurityGroup.addIngressRule(
      ec2.Peer.ipv4(props.vpc.vpcCidrBlock),
      ec2.Port.allTraffic(),
      'Allow all traffic from within the VPC.',
    );
    albSecurityGroup.connections.allowFrom(
      albSecurityGroup,
      ec2.Port.allTraffic(),
      'Allow all traffic within ALB security group',
    );
    albSecurityGroup.addIngressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.HTTPS,
      'Allow HTTPS access from Internet.',
    );

    props.config.voiceAssistant.voicebot.ingress!['alb.ingress.kubernetes.io/security-groups'] = albSecurityGroup.securityGroupId;

    const stunnerGatewayOperatorChartAsset = new s3_assets.Asset(this, 'StunnerGatewayOperatorChartAsset', {
      path: path.join(__dirname, '../../../charts/stunner-gateway-operator/'),
    });
    stunnerGatewayOperatorChartAsset.grantRead(props.helmDeployRole);
    stunnerGatewayOperatorChartAsset.node.addDependency(serviceAccount);

    const stunnerGatewayOperatorHelmChart = props.cluster.addHelmChart('StunnerGatewayOperator', {
      release: 'stunner-gateway-operator',
      chartAsset: stunnerGatewayOperatorChartAsset,
      namespace: props.config.voiceAssistant.namespace,
      wait: true,
      values: {
        stunnerGatewayOperator: {
          deployment: {
            replicas: props.config.voiceAssistant.stunner.gatewayOperator.replicas,
            nodeSelector: {
              'app/stunner': 'enabled',
            },
            container: {
              manager: {
                image: {
                  name: stunnerGatewayOperatorImage,
                  pullPolicy: props.config.voiceAssistant.stunner.gatewayOperator.pullPolicy,
                },
              },
            },
          },
          dataplane: {
            spec: {
              replicas: props.config.voiceAssistant.stunner.dataplane.replicas,
              image: {
                name: stunnerdImage,
                pullPolicy: props.config.voiceAssistant.stunner.dataplane.pullPolicy,
              },
            },
          },
        },
        stunnerAuthService: {
          deployment: {
            replicas: props.config.voiceAssistant.stunner.authService.replicas,
            nodeSelector: {
              'app/stunner': 'enabled',
            },
            container: {
              authService: {
                image: {
                  name: stunnerAuthServerImage,
                  pullPolicy: props.config.voiceAssistant.stunner.authService.pullPolicy,
                },
              },
            },
          },
        },
      },
      timeout: Duration.minutes(10),
    });
    stunnerGatewayOperatorHelmChart.node.addDependency(stunnerGatewayOperatorChartAsset);

    const stunnerManifest = [
      {
        apiVersion: 'stunner.l7mp.io/v1',
        kind: 'GatewayConfig',
        metadata: {
          name: 'stunner-gatewayconfig',
          namespace: props.config.voiceAssistant.namespace,
        },
        spec: {
          realm: 'stunner.l7mp.io',
          authType: 'plaintext',
          userName: props.config.voiceAssistant.stunner.username,
          password: props.config.voiceAssistant.stunner.password,
          loadBalancerServiceAnnotations: props.config.voiceAssistant.stunner.loadBalancerServiceAnnotations,
        },
      },
      {
        apiVersion: 'gateway.networking.k8s.io/v1',
        kind: 'GatewayClass',
        metadata: {
          name: 'stunner-gatewayclass',
          namespace: props.config.voiceAssistant.namespace,
        },
        spec: {
          controllerName: 'stunner.l7mp.io/gateway-operator',
          parametersRef: {
            group: 'stunner.l7mp.io',
            kind: 'GatewayConfig',
            name: 'stunner-gatewayconfig',
            namespace: props.config.voiceAssistant.namespace,
          },
          description: 'STUNner is a WebRTC ingress gateway for Kubernetes',
        },
      },
      {
        apiVersion: 'gateway.networking.k8s.io/v1',
        kind: 'Gateway',
        metadata: {
          name: 'stunner-gateway',
          namespace: props.config.voiceAssistant.namespace,
          annotations: {
            'stunner.l7mp.io/service-type': 'LoadBalancer',
            'stunner.l7mp.io/enable-mixed-protocol-lb': 'true',
            'service.beta.kubernetes.io/aws-load-balancer-healthcheck-path': '/live',
            'service.beta.kubernetes.io/aws-load-balancer-healthcheck-port': '8086',
            'service.beta.kubernetes.io/aws-load-balancer-healthcheck-protocol': 'HTTP',
          },
        },
        spec: {
          gatewayClassName: 'stunner-gatewayclass',
          listeners: [
            { name: 'udp-listener', port: 3478, protocol: 'TURN-UDP' },
            { name: 'tcp-listener', port: 3480, protocol: 'TURN-TCP' },
          ],
        },
      },
      {
        apiVersion: 'autoscaling/v2',
        kind: 'HorizontalPodAutoscaler',
        metadata: {
          name: 'hpa-stunner-gateway',
          namespace: props.config.voiceAssistant.namespace,
        },
        spec: {
          scaleTargetRef: {
            apiVersion: 'apps/v1',
            kind: 'Deployment',
            name: 'stunner-gateway',
          },
          minReplicas: props.config.voiceAssistant.stunner.minReplicas,
          maxReplicas: props.config.voiceAssistant.stunner.maxReplicas,
          metrics: [
            {
              type: 'Resource',
              resource: {
                name: 'cpu',
                target: {
                  type: 'Utilization',
                  averageUtilization: 300,
                },
              },
            },
          ],
        },
      },
    ];

    const stunnerKubernetesManifest = new eks.KubernetesManifest(this, 'StunnerManifest', {
      cluster: props.cluster,
      overwrite: props.config.voiceAssistant.overwrite,
      prune: props.config.voiceAssistant.prune,
      manifest: stunnerManifest,
    });
    stunnerKubernetesManifest.node.addDependency(stunnerGatewayOperatorHelmChart);

    const stunnerLoadBalancerHostName = props.cluster.getServiceLoadBalancerAddress('stunner-gateway', {
      namespace: props.config.voiceAssistant.namespace,
    }).toString();

    const cfnStunnerLoadBalancerHostName = new CfnOutput(this, 'StunnerLoadBalancerHostName', {
      value: stunnerLoadBalancerHostName,
      description: 'The DNS name of the STUNner NLB',
    });
    cfnStunnerLoadBalancerHostName.overrideLogicalId('StunnerLoadBalancerHostName');

    const configYaml = loadYaml(path.join(__dirname, 'config.template.yaml'), {
      PORT: props.config.voiceAssistant.voicebot.port.toString(),
      STUNNER_LOADBALANCER_HOSTNAME: stunnerLoadBalancerHostName,
    });

    const voicebotConfigMap = new eks.KubernetesManifest(this, 'VoicebotConfigMap', {
      cluster: props.cluster,
      overwrite: props.config.voiceAssistant.overwrite,
      prune: props.config.voiceAssistant.prune,
      manifest: [{
        apiVersion: 'v1',
        kind: 'ConfigMap',
        metadata: {
          name: 'app-config',
          namespace: props.config.voiceAssistant.namespace,
        },
        data: {
          'config.yaml': yaml.dump(configYaml),
        },
      }],
    });

    const voicebotIngress = new eks.KubernetesManifest(this, 'VoicebotIngress', {
      cluster: props.cluster,
      overwrite: props.config.voiceAssistant.overwrite,
      prune: props.config.voiceAssistant.prune,
      manifest: [{
        apiVersion: 'networking.k8s.io/v1',
        kind: 'Ingress',
        metadata: {
          name: `${props.config.voiceAssistant.voicebot.name}-ingress-alb`,
          namespace: props.config.voiceAssistant.namespace,
          labels: {
            app: props.config.voiceAssistant.voicebot.name,
          },
          annotations: props.config.voiceAssistant.voicebot.ingress,
        },
        spec: {
          ingressClassName: 'alb',
          rules: [{
            http: {
              paths: [{
                path: '/',
                pathType: 'Prefix',
                backend: {
                  service: {
                    name: props.config.voiceAssistant.voicebot.name,
                    port: {
                      number: props.config.voiceAssistant.voicebot.port,
                    },
                  },
                },
              }],
            },
          }],
        },
      }],
    });
    voicebotIngress.node.addDependency(voicebotConfigMap);

    const voicebotService = new eks.KubernetesManifest(this, 'VoicebotService', {
      cluster: props.cluster,
      overwrite: props.config.voiceAssistant.overwrite,
      prune: props.config.voiceAssistant.prune,
      manifest: [{
        apiVersion: 'v1',
        kind: 'Service',
        metadata: {
          name: props.config.voiceAssistant.voicebot.name,
          namespace: props.config.voiceAssistant.namespace,
          labels: {
            app: props.config.voiceAssistant.voicebot.name,
          },
        },
        spec: {
          ports: [{
            port: props.config.voiceAssistant.voicebot.port,
            protocol: 'TCP',
          }],
          selector: {
            app: props.config.voiceAssistant.voicebot.name,
            tier: 'frontend',
          },
        },
      }],
    });
    voicebotService.node.addDependency(voicebotIngress);

    const voicebotDeployment = new eks.KubernetesManifest(this, 'VoicebotDeployment', {
      cluster: props.cluster,
      overwrite: props.config.voiceAssistant.overwrite,
      prune: props.config.voiceAssistant.prune,
      manifest: [{
        apiVersion: 'apps/v1',
        kind: 'Deployment',
        metadata: {
          name: props.config.voiceAssistant.voicebot.name,
          namespace: props.config.voiceAssistant.namespace,
          labels: {
            app: props.config.voiceAssistant.voicebot.name,
          },
        },
        spec: {
          replicas: 1,
          strategy: {
            type: 'Recreate',
          },
          selector: {
            matchLabels: {
              app: props.config.voiceAssistant.voicebot.name,
            },
          },
          template: {
            metadata: {
              labels: {
                app: props.config.voiceAssistant.voicebot.name,
                tier: 'frontend',
              },
            },
            spec: {
              serviceAccountName: 'voicebot',
              securityContext: {
                runAsUser: 1001,
                runAsGroup: 1001,
              },
              containers: [{
                image: voicebotImage,
                name: props.config.voiceAssistant.voicebot.name,
                command: ['/bin/bash', '-c'],
                args: props.config.voiceAssistant.voicebot.args,
                imagePullPolicy: 'Always',
                ports: [{
                  containerPort: props.config.voiceAssistant.voicebot.port,
                  name: props.config.voiceAssistant.voicebot.name,
                }],
                resources: {
                  requests: {
                    cpu: props.config.voiceAssistant.voicebot.resources.requests.cpu,
                    memory: props.config.voiceAssistant.voicebot.resources.requests.memory,
                  },
                  limits: {
                    cpu: props.config.voiceAssistant.voicebot.resources.requests.cpu,
                    memory: props.config.voiceAssistant.voicebot.resources.requests.memory,
                  },
                },
                volumeMounts: [{
                  name: 'config-volume',
                  mountPath: '/etc/voicebot',
                  readOnly: true,
                }],
                env: [
                  {
                    name: 'PATH',
                    value: '/var/lib/voicebot/.conda/envs/voicebot/bin:/usr/local/nvidia/bin:/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                  },
                  {
                    name: 'TABLE_NAME',
                    value: metadataTable.tableName,
                  },
                  {
                    name: 'AWS_REGION_NAME',
                    value: Aws.REGION,
                  },
                  {
                    name: 'SECRET_ARN',
                    value: secret.secretArn,
                  },
                ],
              }],
              volumes: [{
                name: 'config-volume',
                configMap: {
                  name: 'app-config',
                  items: [{
                    key: 'config.yaml',
                    path: 'config.yaml',
                  }],
                },
              }],
              nodeSelector: {
                'app/voicebot': 'enabled',
              },
            },
          },
        },
      }],
    });
    voicebotDeployment.node.addDependency(voicebotService);
    voicebotDeployment.node.addDependency(stunnerKubernetesManifest);

    const voicebotLoadBalancerHostName = props.cluster.getIngressLoadBalancerAddress(`${props.config.voiceAssistant.voicebot.name}-ingress-alb`, {
      namespace: props.config.voiceAssistant.namespace,
    }).toString();

    const cfnVoicebotLoadBalancerHostName = new CfnOutput(this, 'VoicebotLoadBalancerHostName', {
      value: voicebotLoadBalancerHostName,
      description: 'The DNS name of the Voicebot',
    });
    cfnVoicebotLoadBalancerHostName.overrideLogicalId('VoicebotLoadBalancerHostName');

    const stunnerRouteManifest = [
      {
        apiVersion: 'stunner.l7mp.io/v1',
        kind: 'UDPRoute',
        metadata: {
          name: props.config.voiceAssistant.voicebot.name,
          namespace: props.config.voiceAssistant.namespace,
        },
        spec: {
          parentRefs: [{ name: 'stunner-gateway' }],
          rules: [{
            backendRefs: [
              { name: props.config.voiceAssistant.voicebot.name, namespace: props.config.voiceAssistant.namespace },
            ],
          }],
        },
      },
    ];

    const stunnerRoute = new eks.KubernetesManifest(this, 'StunnerRoute', {
      cluster: props.cluster,
      overwrite: props.config.voiceAssistant.overwrite,
      prune: props.config.voiceAssistant.prune,
      manifest: stunnerRouteManifest,
    });
    stunnerRoute.node.addDependency(voicebotDeployment);
  }
}