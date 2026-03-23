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
import { Aws, Fn, Stack } from 'aws-cdk-lib';
import * as yaml from 'js-yaml';
import { template } from 'lodash';


export function getShortIdOfStack(stack: Stack): string {
  return Fn.select(0, Fn.split('-', Fn.select(2, Fn.split('/', stack.stackId))));
}

export function getShortIdOfStackWithRegion(stack: Stack): string {
  return `${Aws.REGION}-${getShortIdOfStack(stack)}`;
}

export function generateRandomPassword(length: number): string {
  const lowerCase = 'abcdefghijklmnopqrstuvwxyz';
  const upperCase = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
  const numbers = '0123456789';
  const specialChars = '!#$%&*+-._';

  // Ensure at least one character from each category
  const passwordArray: string[] = [];
  passwordArray.push(lowerCase[Math.floor(Math.random() * lowerCase.length)]);
  passwordArray.push(upperCase[Math.floor(Math.random() * upperCase.length)]);
  passwordArray.push(numbers[Math.floor(Math.random() * numbers.length)]);
  passwordArray.push(specialChars[Math.floor(Math.random() * specialChars.length)]);

  // Fill the rest of the password length with random characters from all categories
  const allChars = lowerCase + upperCase + numbers + specialChars;
  for (let i = 4; i < length; i++) {
    const randomIndex = Math.floor(Math.random() * allChars.length);
    passwordArray.push(allChars[randomIndex]);
  }

  // Shuffle the password array to ensure randomness
  const shuffledPassword = passwordArray.sort(() => 0.5 - Math.random()).join('');

  return shuffledPassword;
}


export function loadYaml(filePath: string, variables: { [key: string]: string }): any {
  try {
    const fileContent = fs.readFileSync(filePath, 'utf8');

    const compiled = template(fileContent, {
      interpolate: /{{([\s\S]+?)}}/g,
    });

    const replacedContent = compiled(variables);

    return yaml.load(replacedContent);
  } catch (error) {
    throw new Error(`Failed to load YAML file: ${(<Error>error).message}`);
  }
}


