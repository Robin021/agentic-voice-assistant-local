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

export const ASSETS_TAG_KAY = 'industry-assets';
export const ASSETS_NAME = 'AgenticVoiceAssistantOnAWS';
export const ASSETS_SHORT_NAME = 'VoiceAssistant';
export const KUBERNETES_NAMESPACE = 'voice-assistant';

// export const GCR_REGISTRY = '048912060910.dkr.ecr.cn-northwest-1.amazonaws.com.cn/dockerhub/';
// Generate a 6-character random string consisting of numbers and letters
// export const AWS_RESOURCE_SUFFIX = Math.random().toString(36).slice(2, 8).toUpperCase();

/**
 * Instance map for the EC2 instances
 * See https://aws.amazon.com/ec2/instance-types for more information
 *
 * c - vCPUs, m - Memory in GB
 */
export const EC2_GPU_INSTANCE_TYPE = [
  'g5.large',
  'g5.2xlarge',
  'g5.4xlarge',
  'g5.8xlarge',
  'g5.12xlarge',
  'g5.16xlarge',
  'g5.24xlarge',
  'g5.48xlarge',
  'g6.large',
  'g6.2xlarge',
  'g6.4xlarge',
  'g6.8xlarge',
  'g6.12xlarge',
  'g6.16xlarge',
  'g6.24xlarge',
  'g6.48xlarge',
];

export const EC2_GPU_INSTANCE_GCR_TYPE = [
  'g5.large',
  'g5.2xlarge',
  'g5.4xlarge',
  'g5.8xlarge',
  'g5.12xlarge',
  'g5.16xlarge',
  'g5.24xlarge',
  'g5.48xlarge',
];

/**
 * Utility type for values passed to Helm or GitOps applications.
 */
export type Values = {
  [key: string]: any;
};

