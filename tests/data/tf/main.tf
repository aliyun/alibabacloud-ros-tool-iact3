module "my_vpc" {
  source      = "./modules/vpc"
}
resource "alicloud_vswitch" "vsw" {
  vpc_id            = "${module.my_vpc.vpc_id}"
  cidr_block        = "172.16.0.0/21"
  availability_zone = "cn-shanghai-b"
}
output "vsw_id" {
  value = "${alicloud_vswitch.vsw.id}"
}