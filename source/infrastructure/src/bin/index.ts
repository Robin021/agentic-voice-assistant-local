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

import { Stack, StackProps } from 'aws-cdk-lib';
import { KubernetesManifest } from 'aws-cdk-lib/aws-eks';
import { Construct } from 'constructs';
import { SystemConfig } from '../configs/systemConfig';
import { ALBControllerConstruct } from '../lib/aws-load-balancer-controller/aws-load-balancer-controller';
import { EKSConstruct } from '../lib/eks';
import { MetricsServerConstruct } from '../lib/metrics-server/metrics-server';
import { NvidiaDevicePluginConstruct } from '../lib/nvidia-device-plugin/nvidia-device-plugin';
import { VoiceAssistantHelmConstruct } from '../lib/voice-assistant/voice-assistant-helm';
import { VPCConstruct } from '../lib/vpc';


interface AgenticVoiceAssistantProps extends StackProps {
  config: SystemConfig;
}
export class AgenticVoiceAssistantStack extends Stack {

  constructor(scope: Construct, id: string, props: AgenticVoiceAssistantProps) {
    super(scope, id, props);

    const config = props.config;

    const vpc = new VPCConstruct(this, 'VPC', {
      config: config,
    });

    const eks = new EKSConstruct(this, 'EKS', {
      vpc: vpc.vpc,
      config: config,
    });
    eks.node.addDependency(vpc);

    const ns = new KubernetesManifest(this, 'VoiceAssistantNamespace', {
      cluster: eks.cluster,
      overwrite: props.config.voiceAssistant.overwrite,
      prune: props.config.voiceAssistant.prune,
      manifest: [{
        apiVersion: 'v1',
        kind: 'Namespace',
        metadata: { name: props.config.voiceAssistant.namespace },
      }],
    });

    new KubernetesManifest(this, 'NvidiaDevicePluginConfig', {
      cluster: eks.cluster,
      manifest: [
        {
          apiVersion: 'v1',
          kind: 'ConfigMap',
          metadata: {
            name: 'nvidia-device-plugin-config',
            namespace: 'kube-system',
          },
          data: {
            any: `version: v1
flags:
  migStrategy: none
sharing:
  timeSlicing:
    resources:
    - name: nvidia.com/gpu
      replicas: 4`,
          },
        },
      ],
    });

    if (process.env.DEPLOY_PLUGINS === 'true') {
      new MetricsServerConstruct(this, 'MetricsServer', {
        cluster: eks.cluster,
        helmDeployRole: eks.helmDeployRole,
      });

      new NvidiaDevicePluginConstruct(this, 'NvidiaDevicePlugin', {
        cluster: eks.cluster,
        helmDeployRole: eks.helmDeployRole,
      });

      new ALBControllerConstruct(this, 'ALBController', {
        cluster: eks.cluster,
        helmDeployRole: eks.helmDeployRole,
      });

      if (process.env.DEPLOY_PODS === 'true') {
        new VoiceAssistantHelmConstruct(this, 'VoiceAssistantHelm', {
          config: config,
          vpc: vpc.vpc,
          cluster: eks.cluster,
          helmDeployRole: eks.helmDeployRole,
          namespace: ns,
        });
      };
    };
  }
}
