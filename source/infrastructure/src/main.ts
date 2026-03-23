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

import { App, Tags, Aspects } from 'aws-cdk-lib';
import { AwsSolutionsChecks, NagSuppressions } from 'cdk-nag';
import { AgenticVoiceAssistantStack } from './bin';
import { getConfig } from './config';
import { ASSETS_NAME } from './configs/constants';

const app = new App();

Aspects.of(app).add(new AwsSolutionsChecks({ verbose: true }));
Tags.of(app).add('pcn:finance:project', 'aigc');

const config = getConfig();

const agenticVoiceAssistant = new AgenticVoiceAssistantStack(app, ASSETS_NAME, {
  env: {
    region: process.env.CDK_DEFAULT_REGION,
    account: process.env.CDK_DEFAULT_ACCOUNT,
  },
  config,
});

NagSuppressions.addStackSuppressions(agenticVoiceAssistant, [
  {
    id: 'AwsSolutions-IAM4',
    reason: 'These policies is used by CDK Customer Resource lambda',
  },
  {
    id: 'AwsSolutions-IAM5',
    reason: 'The managed policy needs to use any resources, mainly for EKS Cluster',
  },
  {
    id: 'AwsSolutions-EKS2',
    reason: 'EKS control plane logs will enable based on demand',
  },
  {
    id: 'AwsSolutions-DDB3',
    reason: 'Point-in-time Recovery will be enabled based on demand',
  },
]);

// EKS Task Definition suppression
NagSuppressions.addResourceSuppressionsByPath(agenticVoiceAssistant, '/AgenticVoiceAssistantOnAWS/@aws-cdk--aws-eks.ClusterResourceProvider/OnEventHandler/ServiceRole/Resource', [
  {
    id: 'AwsSolutions-IAM4',
    reason: 'These policies is used by EKS',
  },
  {
    id: 'AwsSolutions-IAM5',
    reason: 'The managed policy needs to use any resources, mainly for EKS Cluster',
  },
]);
NagSuppressions.addResourceSuppressionsByPath(agenticVoiceAssistant, '/AgenticVoiceAssistantOnAWS/@aws-cdk--aws-eks.ClusterResourceProvider/IsCompleteHandler/ServiceRole/Resource', [
  {
    id: 'AwsSolutions-IAM4',
    reason: 'These policies is used by EKS',
  },
  {
    id: 'AwsSolutions-IAM5',
    reason: 'The managed policy needs to use any resources, mainly for EKS Cluster',
  },
]);
NagSuppressions.addResourceSuppressionsByPath(agenticVoiceAssistant, '/AgenticVoiceAssistantOnAWS/@aws-cdk--aws-eks.ClusterResourceProvider/Provider/framework-onTimeout/ServiceRole/Resource', [
  {
    id: 'AwsSolutions-IAM4',
    reason: 'These policies is used by EKS',
  },
  {
    id: 'AwsSolutions-IAM5',
    reason: 'The managed policy needs to use any resources, mainly for EKS Cluster',
  },
]);
NagSuppressions.addResourceSuppressionsByPath(agenticVoiceAssistant, '/AgenticVoiceAssistantOnAWS/@aws-cdk--aws-eks.KubectlProvider/Provider/framework-onEvent/ServiceRole/DefaultPolicy/Resource', [
  {
    id: 'AwsSolutions-IAM4',
    reason: 'These policies is used by EKS',
  },
  {
    id: 'AwsSolutions-IAM5',
    reason: 'The managed policy needs to use any resources, mainly for EKS Cluster',
  },
]);
NagSuppressions.addResourceSuppressionsByPath(agenticVoiceAssistant, '/AgenticVoiceAssistantOnAWS/@aws-cdk--aws-eks.KubectlProvider/Provider/framework-onEvent/ServiceRole/Resource', [
  {
    id: 'AwsSolutions-IAM4',
    reason: 'These policies is used by EKS',
  },
  {
    id: 'AwsSolutions-IAM5',
    reason: 'The managed policy needs to use any resources, mainly for EKS Cluster',
  },
]);
NagSuppressions.addResourceSuppressionsByPath(agenticVoiceAssistant, '/AgenticVoiceAssistantOnAWS/@aws-cdk--aws-eks.ClusterResourceProvider/Provider/framework-onEvent/ServiceRole/Resource', [
  {
    id: 'AwsSolutions-IAM4',
    reason: 'These policies is used by EKS',
  },
  {
    id: 'AwsSolutions-IAM5',
    reason: 'The managed policy needs to use any resources, mainly for EKS Cluster',
  },
]);
NagSuppressions.addResourceSuppressionsByPath(agenticVoiceAssistant, '/AgenticVoiceAssistantOnAWS/@aws-cdk--aws-eks.ClusterResourceProvider/Provider/framework-isComplete/ServiceRole/Resource', [
  {
    id: 'AwsSolutions-IAM4',
    reason: 'These policies is used by EKS',
  },
  {
    id: 'AwsSolutions-IAM5',
    reason: 'The managed policy needs to use any resources, mainly for EKS Cluster',
  },
]);
NagSuppressions.addResourceSuppressionsByPath(agenticVoiceAssistant, '/AgenticVoiceAssistantOnAWS/@aws-cdk--aws-eks.ClusterResourceProvider/Provider/framework-onEvent/ServiceRole/DefaultPolicy/Resource', [
  {
    id: 'AwsSolutions-IAM5',
    reason: 'The managed policy needs to use any resources, mainly for EKS Cluster',
  },
]);
NagSuppressions.addResourceSuppressionsByPath(agenticVoiceAssistant, '/AgenticVoiceAssistantOnAWS/@aws-cdk--aws-eks.ClusterResourceProvider/Provider/framework-isComplete/ServiceRole/DefaultPolicy/Resource', [
  {
    id: 'AwsSolutions-IAM5',
    reason: 'The managed policy needs to use any resources, mainly for EKS Cluster',
  },
]);
NagSuppressions.addResourceSuppressionsByPath(agenticVoiceAssistant, '/AgenticVoiceAssistantOnAWS/@aws-cdk--aws-eks.ClusterResourceProvider/Provider/framework-onTimeout/ServiceRole/DefaultPolicy/Resource', [
  {
    id: 'AwsSolutions-IAM5',
    reason: 'The managed policy needs to use any resources, mainly for EKS Cluster',
  },
]);
NagSuppressions.addResourceSuppressionsByPath(agenticVoiceAssistant, '/AgenticVoiceAssistantOnAWS/@aws-cdk--aws-eks.ClusterResourceProvider/Provider/waiter-state-machine/Role/DefaultPolicy/Resource', [
  {
    id: 'AwsSolutions-IAM4',
    reason: 'These policies is used by EKS',
  },
  {
    id: 'AwsSolutions-IAM5',
    reason: 'The managed policy needs to use any resources, mainly for EKS Cluster',
  },
  {
    id: 'AwsSolutions-SF1',
    reason: 'Step Function logs will be enabled based on demand',
  },
]);
NagSuppressions.addResourceSuppressionsByPath(agenticVoiceAssistant, '/AgenticVoiceAssistantOnAWS/@aws-cdk--aws-eks.ClusterResourceProvider/Provider/waiter-state-machine/Resource', [
  {
    id: 'AwsSolutions-SF1',
    reason: 'Step Function logs will be enabled based on demand',
  },
  {
    id: 'AwsSolutions-SF2',
    reason: 'X-Ray tracing will be enabled based on demand',
  },
]);
NagSuppressions.addResourceSuppressionsByPath(agenticVoiceAssistant, '/AgenticVoiceAssistantOnAWS/@aws-cdk--aws-eks.KubectlProvider/Handler/Resource', [
  {
    id: 'AwsSolutions-L1',
    reason: 'This lambda is created by cdk.',
  },
]);

if (process.env.DEPLOY_PODS === 'true') {
  // ALB suppression
  NagSuppressions.addResourceSuppressionsByPath(agenticVoiceAssistant, '/AgenticVoiceAssistantOnAWS/VoiceAssistantHelm/Voicebot/ALBSG/Resource', [
    {
      id: 'AwsSolutions-EC23',
      reason: 'This security group only exposes port 443 to the internet.',
    },
  ]);
  // Secret suppression
  NagSuppressions.addResourceSuppressionsByPath(agenticVoiceAssistant, '/AgenticVoiceAssistantOnAWS/VoiceAssistantHelm/Voicebot/Secret/Resource', [
    {
      id: 'AwsSolutions-SMG4',
      reason: 'This key is used to store secrets that do not require enabling automatic rotation.',
    },
  ]);
}
NagSuppressions.addResourceSuppressionsByPath(agenticVoiceAssistant, '/AgenticVoiceAssistantOnAWS/VPC/NewVPC/Resource', [
  {
    id: 'AwsSolutions-VPC7',
    reason: 'VPC Flow Logs will be enabled based on demand',
  },
]);
app.synth();
