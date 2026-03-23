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

import { existsSync, readFileSync } from 'fs';
import { KubernetesVersion } from 'aws-cdk-lib/aws-eks';
import { KUBERNETES_NAMESPACE } from './configs/constants';
import { SystemConfig } from './configs/systemConfig';
import { generateRandomPassword } from './lib/utils';

export const DEFAULT_CONFIG: SystemConfig = {
  isChinaRegion: false,
  network: {},
  cluster: {
    version: KubernetesVersion.V1_32.version,
    // at least 2 ids
    vpcSubnetIds: [],
    managedNodeGroups: {
      gpu: {
        desiredSize: 1,
        minSize: 1,
        maxSize: 6,
        instanceType: 'g5.2xlarge',
        diskSize: 500,
        workerNodeSubnetIds: [],
      },
      cpu: {
        desiredSize: 1,
        minSize: 1,
        maxSize: 6,
        instanceType: 'm6i.xlarge',
        diskSize: 500,
        workerNodeSubnetIds: [],
      },
    },
  },
  voiceAssistant: {
    namespace: KUBERNETES_NAMESPACE,
    overwrite: true,
    prune: false,
    stunner: {
      username: 'stunneruser',
      password: generateRandomPassword(16),
      loadBalancerServiceAnnotations: {
        'service.beta.kubernetes.io/aws-load-balancer-scheme': 'internet-facing',
        'service.beta.kubernetes.io/aws-load-balancer-type': 'external',
        'service.beta.kubernetes.io/aws-load-balancer-nlb-target-type': 'ip',
        'service.beta.kubernetes.io/aws-load-balancer-cross-zone-load-balancing-enabled': 'true',
        'service.beta.kubernetes.io/aws-load-balancer-target-group-attributes': 'stickiness.enabled=true,stickiness.type=source_ip',
      },
      gatewayOperator: {
        image: '',
        replicas: 1,
        pullPolicy: 'IfNotPresent',
      },
      dataplane: {
        image: '',
        replicas: 1,
        pullPolicy: 'IfNotPresent',
      },
      authService: {
        image: '',
        replicas: 1,
        pullPolicy: 'IfNotPresent',
      },
      minReplicas: 1,
      maxReplicas: 4,
    },
    stt: {
      image: '',
      name: 'sensevoice',
      port: 50000,
      replicas: 1,
      args: ['python -u server.py --port 50000'],
      resources: {
        requests: {
          gpu: 1,
          cpu: '2000m',
          memory: '4096Mi',
        },
        limits: {
          gpu: 1,
          cpu: '4000m',
          memory: '8192Mi',
        },
      },
    },
    tts: {
      image: '',
      name: 'cosyvoice',
      port: 50001,
      replicas: 1,
      args: ['cd async_cosyvoice/runtime/fastapi && python server.py --load_jit --load_trt --fp16 --port 50001'],
      resources: {
        requests: {
          gpu: 2,
          cpu: '2000m',
          memory: '8192Mi',
        },
        limits: {
          gpu: 2,
          cpu: '4000m',
          memory: '10240Mi',
        },
      },
    },
    contextRelevance: {
      image: 'public.ecr.aws/deep-learning-containers/vllm:0.9.2-gpu-py312-cu128-ubuntu22.04-ec2-v1.5',
      name: 'qwen3-0p6b',
      port: 8000,
      replicas: 1,
      args: ['vllm serve Qwen/Qwen3-0.6B --max_model_len 1024 --gpu_memory_utilization 0.1 --port 8000'],
      resources: {
        requests: {
          gpu: 1,
          cpu: '2000m',
          memory: '8192Mi',
        },
        limits: {
          gpu: 2,
          cpu: '4000m',
          memory: '8192Mi',
        },
      },
    },
    voicebot: {
      image: '',
      name: 'voicebot',
      port: 8080,
      replicas: 1,
      args: ['python app.py -m ui'],
      resources: {
        requests: {
          cpu: '2000m',
          memory: '4096Mi',
        },
        limits: {
          cpu: '8000m',
          memory: '16384Mi',
        },
      },
      ingress: {
        'alb.ingress.kubernetes.io/scheme': 'internet-facing',
        'alb.ingress.kubernetes.io/target-type': 'ip',
        'alb.ingress.kubernetes.io/listen-ports': '[{"HTTPS": 443}]',
        'alb.ingress.kubernetes.io/healthcheck-path': '/',
        'alb.ingress.kubernetes.io/manage-backend-security-group-rules': 'true',
      },
    },
    litellmParams: {
      model: 'bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0',
      aws_region_name: 'us-east-1',
    },
  },
};

export function getConfig(): SystemConfig {
  if (existsSync('./src/config.json')) {
    return JSON.parse(
      readFileSync('./src/config.json').toString('utf8'),
    ) as SystemConfig;
  }
  // Default config
  return DEFAULT_CONFIG;
}

export const config: SystemConfig = getConfig();
