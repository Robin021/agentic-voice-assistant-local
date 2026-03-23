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

export interface EksTaintsConfig {
  vectorDb: {
    key: string;
    value: string;
  };
}

interface NodeGroupOptions {
  desiredSize: number; // desired number of nodes
  minSize: number; // minimum number of nodes
  maxSize: number; // maximum number of nodes
  instanceType: string; // instance type for the nodes
  diskSize: number; // disk size for the nodes
  workerNodeSubnetIds: string[]; // subnets for the EKS cluster worker nodes
}
interface managedNodeGroups {
  gpu: NodeGroupOptions;
  cpu: NodeGroupOptions;
}

export interface EksClusterConfig {
  version: string; // version of the EKS cluster
  clusterName?: string; //optional eks cluster
  managedNodeGroups: managedNodeGroups; // managed node groups for the EKS cluster
  vpcSubnetIds: string[]; // subnets for the EKS cluster control plane
}
