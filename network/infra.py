from typing import cast

from aws_cdk import aws_ec2 as ec2
from aws_cdk import core as cdk


class EKSEnvironmentNetwork(cdk.Construct):
    def __init__(self, scope: cdk.Construct, id_: str):
        super().__init__(scope, id_)

        self.vpc: ec2.Vpc = self._create_vpc()

        self.vpce_subnets = (
            self.vpc.select_subnets(subnet_group_name="Private")
        )
        self._vpc_security_group = ec2.SecurityGroup(
            self, "vpc-sg", vpc=cast(ec2.IVpc, self.vpc), allow_all_outbound=False
        )
        # Adding ingress rule to VPC CIDR
        self._vpc_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(self.vpc.vpc_cidr_block), connection=ec2.Port.all_tcp()
        )
        self._create_vpc_endpoints()

    def _create_vpc(self) -> ec2.Vpc:

        subnet_configuration = [
            ec2.SubnetConfiguration(
                name="eks-control-plane",
                subnet_type=ec2.SubnetType.PRIVATE,
                cidr_mask=28
            ),
            ec2.SubnetConfiguration(
                name="Public",
                subnet_type=ec2.SubnetType.PUBLIC,
                cidr_mask=24
            ),
            ec2.SubnetConfiguration(
                name="Private",
                subnet_type=ec2.SubnetType.PRIVATE,
                cidr_mask=20
            ),
        ]

        vpc = ec2.Vpc(
            scope=self,
            id="vpc",
            default_instance_tenancy=ec2.DefaultInstanceTenancy.DEFAULT,
            cidr="10.0.0.0/16",
            enable_dns_hostnames=True,
            enable_dns_support=True,
            max_azs=3,
            subnet_configuration=subnet_configuration,
        )
        return vpc

    def _create_vpc_endpoints(self) -> None:
        vpc_gateway_endpoints = {
            "s3": ec2.GatewayVpcEndpointAwsService.S3,
            "dynamodb": ec2.GatewayVpcEndpointAwsService.DYNAMODB,
        }
        vpc_interface_endpoints = {
            "ecr_docker_endpoint": ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
            "ecr_endpoint": ec2.InterfaceVpcEndpointAwsService.ECR,
            "cloudwatch_endpoint": ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH,
            "cloudwatch_logs_endpoint":
                ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
            "cloudwatch_events": ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_EVENTS,
            "ec2_endpoint": ec2.InterfaceVpcEndpointAwsService.EC2,
            "ecs": ec2.InterfaceVpcEndpointAwsService.ECS,
            "ecs_agent": ec2.InterfaceVpcEndpointAwsService.ECS_AGENT,
            "ecs_telemetry": ec2.InterfaceVpcEndpointAwsService.ECS_TELEMETRY,
            "elb": ec2.InterfaceVpcEndpointAwsService.ELASTIC_LOAD_BALANCING,
            "autoscaling": ec2.InterfaceVpcEndpointAwsService("autoscaling"),
        }

        for name, gateway_vpc_endpoint_service in vpc_gateway_endpoints.items():
            self.vpc.add_gateway_endpoint(
                id=name,
                service=gateway_vpc_endpoint_service,
                subnets=[
                    ec2.SubnetSelection(subnets=self.vpce_subnets.subnets),
                ],
            )

        for name, interface_service in vpc_interface_endpoints.items():
            self.vpc.add_interface_endpoint(
                id=name,
                service=interface_service,
                subnets=ec2.SubnetSelection(subnets=self.vpce_subnets.subnets),
                private_dns_enabled=True,
                security_groups=[cast(ec2.ISecurityGroup, self._vpc_security_group)],
            )
