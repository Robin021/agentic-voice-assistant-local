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

import { IVpc } from 'aws-cdk-lib/aws-ec2';
import * as eks from 'aws-cdk-lib/aws-eks';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import { ContextRelevanceConstruct } from './context-relevance';
import { Speech2TextConstruct } from './speech-to-text';
import { Text2SpeechConstruct } from './text-to-speech';
import { VoicebotConstruct } from './voicebot';
import { SystemConfig } from '../../configs/systemConfig';

export interface VoiceAssistantHelmConstructProps {
  readonly config: SystemConfig;
  readonly vpc: IVpc;
  readonly cluster: eks.Cluster;
  readonly helmDeployRole: iam.Role;
  readonly namespace: eks.KubernetesManifest;
}

export class VoiceAssistantHelmConstruct extends Construct {

  constructor(scope: Construct, id: string, props: VoiceAssistantHelmConstructProps) {
    super(scope, id);

    new VoicebotConstruct(this, 'Voicebot', {
      config: props.config,
      vpc: props.vpc,
      cluster: props.cluster,
      helmDeployRole: props.helmDeployRole,
    });

    new Speech2TextConstruct(this, 'SpeechToText', {
      config: props.config,
      cluster: props.cluster,
    });

    new Text2SpeechConstruct(this, 'TextToSpeech', {
      config: props.config,
      cluster: props.cluster,
    });

    new ContextRelevanceConstruct(this, 'ContextRelevance', {
      config: props.config,
      cluster: props.cluster,
    });
  }
}