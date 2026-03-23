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


import * as fs from 'fs';
import { Command } from '@commander-js/extra-typings';
import Enquirer from 'enquirer';
import merge from 'lodash.merge';
import { LIB_VERSION } from './version';
import { DEFAULT_CONFIG } from '../config';
import { EC2_GPU_INSTANCE_GCR_TYPE, EC2_GPU_INSTANCE_TYPE } from '../configs/constants';
import { SystemConfig } from '../configs/systemConfig';

/**
 * Main entry point
 */

const program = new Command().description(
  'Creates a new chatbot configuration',
);

(async () => {
  program.version(LIB_VERSION);

  program.option('-p, --prefix <prefix>', 'The prefix for the stack');

  program.action(async (options: any) => {
    if (fs.existsSync('./bin/config.json')) {
      const config: SystemConfig = JSON.parse(
        fs.readFileSync('./bin/config.json').toString('utf8'),
      );
      options.vpcId = config.network?.vpcId;
    }
    try {
      await processCreateOptions(options);
    } catch (err) {
      console.error('Could not complete the operation.');
      if (err instanceof Error) {
        console.error(err.message);
      }
      process.exit(1);
    }
  });

  program.parse(process.argv);
})().catch(error => {
  console.error('Error:', error);
  process.exit(1);
});

function createConfig(config: any): void {
  fs.writeFileSync('./src/config.json', JSON.stringify(config, undefined, 2));
  console.log('Configuration written to ./src/config.json');
}

/**
 * Prompts the user for missing options
 *
 * @param options Options provided via the CLI
 * @returns The complete options
 */
async function processCreateOptions(options: any): Promise<void> {
  const questions = [
    {
      type: 'confirm',
      name: 'isChinaRegion',
      message:
        'Do you want to deploy in China region? (selecting false will deploy in global regions)',
      initial: options.isChinaRegion ?? false,
    },
    {
      type: 'confirm',
      name: 'existingVpc',
      message:
        'Do you want to use existing vpc? (selecting false will create a new vpc)',
      initial: options.vpcId ? true : false,
    },
    {
      type: 'input',
      name: 'vpcId',
      message: 'Specify existing VpcId (vpc-xxxxxxxxxxxxxxxxx)',
      initial: options.vpcId,
      validate(vpcId: string) {
        return (this as any).skipped ||
          RegExp(/^vpc-[0-9a-f]{8,17}$/i).test(vpcId)
          ? true
          : 'Enter a valid VpcId in vpc-xxxxxxxxxxx format';
      },
      skip(): boolean {
        return !(this as any).state.answers.existingVpc;
      },
    },
    {
      type: 'input',
      name: 'eksClusterName',
      message: 'Customize eks cluster name (empty will generate a name)',
      initial: options.eksClusterName ?? 'voice-assistant',
      validate: (input: string) => {
        if (input.length > 100) {
          return 'Cluster name must be 100 characters or less';
        }

        if (!/^[a-zA-Z0-9]/.test(input)) {
          return 'Cluster name must start with a letter or digit';
        }

        if (!/^[a-zA-Z0-9\-_]+$/.test(input)) {
          return 'Cluster name can only contain letters, digits, hyphens and underscores';
        }

        if (input.endsWith('-') || input.startsWith('-')) {
          return 'Cluster name cannot start or end with a hyphen';
        }

        if (input.includes('--')) {
          return 'Cluster name cannot contain two consecutive hyphens';
        }

        return true;
      },
    },
    {
      type: 'select',
      name: 'eksGPUNodeInstanceType',
      message:
        'Pick the instance type for the EKS GPU nodes',
      hint: 'See https://aws.amazon.com/ec2/instance-types for more information',
      choices: EC2_GPU_INSTANCE_TYPE,
      initial: options.eksGPUNodeInstanceType ?? 'g5.2xlarge',
      skip(): boolean {
        return (this as any).state.answers.isChinaRegion;
      },
    },
    {
      type: 'select',
      name: 'eksGPUNodeInstanceType',
      message:
        'Pick the instance type for the EKS GPU nodes',
      hint: 'See https://aws.amazon.com/ec2/instance-types for more information',
      choices: EC2_GPU_INSTANCE_GCR_TYPE,
      initial: options.eksGPUNodeInstanceType ?? 'g5.2xlarge',
      skip(): boolean {
        return !(this as any).state.answers.isChinaRegion;
      },
    },
    {
      type: 'input',
      name: 'certificateArn',
      message: 'Enter ACM Certificate ARN (required for HTTPS encryption):',
      initial: options.certificateArn,
      validate: (value: string) => {
        if (!value) {
          return 'ACM Certificate ARN is required. Please provide a valid certificate ARN';
        }
        // Regular expression that supports both aws and aws-cn partitions
        const acmArnRegex = /^arn:(aws|aws-cn):acm:[a-z]{2}-[a-z]+-\d:\d{12}:certificate\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
        if (!acmArnRegex.test(value)) {
          return 'Please enter a valid ACM Certificate ARN. Format should be: arn:(aws|aws-cn):acm:region:account-id:certificate/certificate-id';
        }
        return true;
      },
    },
  ];

  const answers: any = await Enquirer.prompt(questions);
  // Create the config object
  const config = merge({}, DEFAULT_CONFIG, {
    isChinaRegion: answers.isChinaRegion,
    network: {
      vpcId: answers.existingVpc ? answers.vpcId.toLowerCase() : undefined,
    },
    cluster: {
      ...DEFAULT_CONFIG.cluster,
      clusterName: answers.eksClusterName,
      managedNodeGroups: {
        gpu: {
          ...DEFAULT_CONFIG.cluster.managedNodeGroups.gpu,
          instanceType: answers.eksGPUNodeInstanceType,
        },
        cpu: DEFAULT_CONFIG.cluster.managedNodeGroups.cpu,
      },
    },
    voiceAssistant: {
      voicebot: {
        ingress: {
          'alb.ingress.kubernetes.io/certificate-arn': answers.certificateArn,
        },
      },
    },
  });

  console.log('\n✨ This is the chosen configuration:\n');
  console.log(JSON.stringify(config, undefined, 2));
  (
    (await Enquirer.prompt([
      {
        type: 'confirm',
        name: 'create',
        message:
          'Do you want to create/update the configuration based on the above settings',
        initial: true,
      },
    ])) as any
  ).create
    ? createConfig(config)
    : console.log('Skipping');
}
