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
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as eks from 'aws-cdk-lib/aws-eks';
import { Construct } from 'constructs';
import { SystemConfig } from '../../configs/systemConfig';

export interface Speech2TextConstructProps {
  readonly config: SystemConfig;
  readonly cluster: eks.Cluster;
}

export class Speech2TextConstruct extends Construct {

  constructor(scope: Construct, id: string, props: Speech2TextConstructProps) {
    super(scope, id);

    let speechToTextImage = props.config.voiceAssistant.stt.image;
    if (!speechToTextImage) {
      const speechToTextImageAsset = new ecr_assets.DockerImageAsset(this, 'SpeechToTextImageAsset', {
        directory: path.join(__dirname, '../../../../../docker/sensevoice'),
      });
      speechToTextImage = speechToTextImageAsset.imageUri;
    };

    const service = new eks.KubernetesManifest(this, 'SpeechToTextService', {
      cluster: props.cluster,
      overwrite: props.config.voiceAssistant.overwrite,
      prune: props.config.voiceAssistant.prune,
      manifest: [{
        apiVersion: 'v1',
        kind: 'Service',
        metadata: {
          name: props.config.voiceAssistant.stt.name,
          namespace: props.config.voiceAssistant.namespace,
          labels: {
            app: props.config.voiceAssistant.stt.name,
          },
        },
        spec: {
          ports: [{
            port: props.config.voiceAssistant.stt.port,
            protocol: 'TCP',
          }],
          selector: {
            app: props.config.voiceAssistant.stt.name,
            tier: 'frontend',
          },
        },
      }],
    });

    const deployment = new eks.KubernetesManifest(this, 'SpeechToTextDeployment', {
      cluster: props.cluster,
      overwrite: props.config.voiceAssistant.overwrite,
      prune: props.config.voiceAssistant.prune,
      manifest: [{
        apiVersion: 'apps/v1',
        kind: 'Deployment',
        metadata: {
          name: props.config.voiceAssistant.stt.name,
          namespace: props.config.voiceAssistant.namespace,
          labels: {
            app: props.config.voiceAssistant.stt.name,
          },
        },
        spec: {
          replicas: props.config.voiceAssistant.stt.replicas,
          strategy: {
            type: 'Recreate',
          },
          selector: {
            matchLabels: {
              app: props.config.voiceAssistant.stt.name,
            },
          },
          template: {
            metadata: {
              labels: {
                app: props.config.voiceAssistant.stt.name,
                tier: 'frontend',
              },
            },
            spec: {
              securityContext: {
                runAsUser: 1001,
                runAsGroup: 1001,
              },
              containers: [{
                image: speechToTextImage,
                name: props.config.voiceAssistant.stt.name,
                command: ['/bin/bash', '-c'],
                args: props.config.voiceAssistant.stt.args,
                imagePullPolicy: 'Always',
                ports: [{
                  containerPort: props.config.voiceAssistant.stt.port,
                  name: props.config.voiceAssistant.stt.name,
                }],
                resources: {
                  requests: {
                    'nvidia.com/gpu': props.config.voiceAssistant.stt.resources.requests.gpu,
                    'cpu': props.config.voiceAssistant.stt.resources.requests.cpu,
                    'memory': props.config.voiceAssistant.stt.resources.requests.memory,
                  },
                  limits: {
                    'nvidia.com/gpu': props.config.voiceAssistant.stt.resources.requests.gpu,
                    'cpu': props.config.voiceAssistant.stt.resources.requests.cpu,
                    'memory': props.config.voiceAssistant.stt.resources.requests.memory,
                  },
                },
                env: [
                  {
                    name: 'SENSEVOICE_DEVICE',
                    value: 'cuda:0',
                  },
                  {
                    name: 'PATH',
                    value: '/var/lib/sensevoice/.conda/envs/sensevoice/bin:/usr/local/nvidia/bin:/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                  },
                ],
              }],
              tolerations: [{
                key: 'nvidia.com/gpu',
                operator: 'Exists',
                effect: 'NoSchedule',
              }],
              nodeSelector: {
                'nvidia.com/gpu.present': 'true',
              },
            },
          },
        },
      }],
    });

    deployment.node.addDependency(service);
  }
}