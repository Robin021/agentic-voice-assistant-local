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

export interface Text2SpeechConstructProps {
  readonly config: SystemConfig;
  readonly cluster: eks.Cluster;
}

export class Text2SpeechConstruct extends Construct {

  constructor(scope: Construct, id: string, props: Text2SpeechConstructProps) {
    super(scope, id);

    let textToSpeechImage = props.config.voiceAssistant.tts.image;
    if (!textToSpeechImage) {
      const textToSpeechImageAsset = new ecr_assets.DockerImageAsset(this, 'TextToSpeechImageAsset', {
        directory: path.join(__dirname, '../../../../../docker/cosyvoice'),
      });
      textToSpeechImage = textToSpeechImageAsset.imageUri;
    };

    const service = new eks.KubernetesManifest(this, 'TextToSpeechService', {
      cluster: props.cluster,
      overwrite: props.config.voiceAssistant.overwrite,
      prune: props.config.voiceAssistant.prune,
      manifest: [{
        apiVersion: 'v1',
        kind: 'Service',
        metadata: {
          name: props.config.voiceAssistant.tts.name,
          namespace: props.config.voiceAssistant.namespace,
          labels: {
            app: props.config.voiceAssistant.tts.name,
          },
        },
        spec: {
          ports: [{
            port: props.config.voiceAssistant.tts.port,
            protocol: 'TCP',
          }],
          selector: {
            app: props.config.voiceAssistant.tts.name,
            tier: 'frontend',
          },
        },
      }],
    });

    const deployment = new eks.KubernetesManifest(this, 'TextToSpeechDeployment', {
      cluster: props.cluster,
      overwrite: props.config.voiceAssistant.overwrite,
      prune: props.config.voiceAssistant.prune,
      manifest: [{
        apiVersion: 'apps/v1',
        kind: 'Deployment',
        metadata: {
          name: props.config.voiceAssistant.tts.name,
          namespace: props.config.voiceAssistant.namespace,
          labels: {
            app: props.config.voiceAssistant.tts.name,
          },
        },
        spec: {
          replicas: props.config.voiceAssistant.tts.replicas,
          strategy: {
            type: 'Recreate',
          },
          selector: {
            matchLabels: {
              app: props.config.voiceAssistant.tts.name,
            },
          },
          template: {
            metadata: {
              labels: {
                app: props.config.voiceAssistant.tts.name,
                tier: 'frontend',
              },
            },
            spec: {
              securityContext: {
                runAsUser: 1001,
                runAsGroup: 1001,
              },
              containers: [{
                image: textToSpeechImage,
                name: props.config.voiceAssistant.tts.name,
                command: ['/bin/bash', '-c'],
                args: props.config.voiceAssistant.tts.args,
                imagePullPolicy: 'Always',
                ports: [{
                  containerPort: props.config.voiceAssistant.tts.port,
                  name: props.config.voiceAssistant.tts.name,
                }],
                resources: {
                  requests: {
                    'nvidia.com/gpu': props.config.voiceAssistant.tts.resources.requests.gpu,
                    'cpu': props.config.voiceAssistant.tts.resources.requests.cpu,
                    'memory': props.config.voiceAssistant.tts.resources.requests.memory,
                  },
                  limits: {
                    'nvidia.com/gpu': props.config.voiceAssistant.tts.resources.requests.gpu,
                    'cpu': props.config.voiceAssistant.tts.resources.requests.cpu,
                    'memory': props.config.voiceAssistant.tts.resources.requests.memory,
                  },
                },
                env: [
                  {
                    name: 'PATH',
                    value: '/var/lib/cosyvoice/.conda/envs/cosyvoice/bin:/usr/local/nvidia/bin:/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                  },
                  {
                    name: 'HF_HOME',
                    value: '/var/lib/cosyvoice',
                  },
                  {
                    name: 'MODELSCOPE_CACHE',
                    value: '/var/lib/cosyvoice',
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