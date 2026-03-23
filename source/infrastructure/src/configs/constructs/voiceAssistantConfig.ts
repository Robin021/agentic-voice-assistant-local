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

export interface StunnerDeploymentSpec {
  replicas: number;
  image?: string;
  pullPolicy: string;
};

export interface StunnerConfig {
  username: string;
  password: string;
  loadBalancerServiceAnnotations: { [key: string]: string };
  gatewayOperator: StunnerDeploymentSpec;
  dataplane: StunnerDeploymentSpec;
  authService: StunnerDeploymentSpec;
  minReplicas: number;
  maxReplicas: number;
};

export interface ComputeResources {
  cpu: string;
  memory: string;
  gpu?: number;
}

export interface ResourceRequirements {
  requests: ComputeResources;
  limits: ComputeResources;
};

export interface KubernetesDeploymentSpec {
  image?: string;
  name: string;
  port: number;
  replicas: number;
  resources: ResourceRequirements;
  args: Array<string>;
  ingress?: { [key: string]: string };
};


export interface VoiceAssistantConfig {
  namespace: string;
  overwrite: boolean;
  prune: boolean;
  stunner: StunnerConfig;
  stt: KubernetesDeploymentSpec;
  tts: KubernetesDeploymentSpec;
  contextRelevance: KubernetesDeploymentSpec;
  voicebot: KubernetesDeploymentSpec;
  litellmParams: { [key: string]: string };
}

