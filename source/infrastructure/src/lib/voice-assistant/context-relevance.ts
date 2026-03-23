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

import * as eks from 'aws-cdk-lib/aws-eks';
import { Construct } from 'constructs';
import { SystemConfig } from '../../configs/systemConfig';

export interface ContextRelevanceConstructProps {
  readonly config: SystemConfig;
  readonly cluster: eks.Cluster;
}

export class ContextRelevanceConstruct extends Construct {

  constructor(scope: Construct, id: string, props: ContextRelevanceConstructProps) {
    super(scope, id);

    const service = new eks.KubernetesManifest(this, 'ContextRelevanceService', {
      cluster: props.cluster,
      overwrite: props.config.voiceAssistant.overwrite,
      prune: props.config.voiceAssistant.prune,
      manifest: [{
        apiVersion: 'v1',
        kind: 'Service',
        metadata: {
          name: props.config.voiceAssistant.contextRelevance.name,
          namespace: props.config.voiceAssistant.namespace,
          labels: {
            app: props.config.voiceAssistant.contextRelevance.name,
          },
        },
        spec: {
          ports: [{
            port: props.config.voiceAssistant.contextRelevance.port,
            protocol: 'TCP',
          }],
          selector: {
            app: props.config.voiceAssistant.contextRelevance.name,
            tier: 'frontend',
          },
        },
      }],
    });

    const deployment = new eks.KubernetesManifest(this, 'ContextRelevanceDeployment', {
      cluster: props.cluster,
      overwrite: props.config.voiceAssistant.overwrite,
      prune: props.config.voiceAssistant.prune,
      manifest: [{
        apiVersion: 'apps/v1',
        kind: 'Deployment',
        metadata: {
          name: props.config.voiceAssistant.contextRelevance.name,
          namespace: props.config.voiceAssistant.namespace,
          labels: {
            app: props.config.voiceAssistant.contextRelevance.name,
          },
        },
        spec: {
          replicas: props.config.voiceAssistant.contextRelevance.replicas,
          strategy: {
            type: 'Recreate',
          },
          selector: {
            matchLabels: {
              app: props.config.voiceAssistant.contextRelevance.name,
            },
          },
          template: {
            metadata: {
              labels: {
                app: props.config.voiceAssistant.contextRelevance.name,
                tier: 'frontend',
              },
            },
            spec: {
              containers: [{
                image: props.config.voiceAssistant.contextRelevance.image,
                name: props.config.voiceAssistant.contextRelevance.name,
                command: ['/bin/bash', '-c'],
                args: props.config.voiceAssistant.contextRelevance.args,
                imagePullPolicy: 'Always',
                ports: [{
                  containerPort: props.config.voiceAssistant.contextRelevance.port,
                  name: props.config.voiceAssistant.contextRelevance.name,
                }],
                resources: {
                  requests: {
                    'nvidia.com/gpu': props.config.voiceAssistant.contextRelevance.resources.requests.gpu,
                    'cpu': props.config.voiceAssistant.contextRelevance.resources.requests.cpu,
                    'memory': props.config.voiceAssistant.contextRelevance.resources.requests.memory,
                  },
                  limits: {
                    'nvidia.com/gpu': props.config.voiceAssistant.contextRelevance.resources.requests.gpu,
                    'cpu': props.config.voiceAssistant.contextRelevance.resources.requests.cpu,
                    'memory': props.config.voiceAssistant.contextRelevance.resources.requests.memory,
                  },
                },
                env: [
                  {
                    name: 'VLLM_USE_MODELSCOPE',
                    value: 'True',
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