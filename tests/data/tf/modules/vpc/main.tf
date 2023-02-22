resource "alicloud_vpc" "vpc" {
  name       = "tf_test"
  cidr_block = "172.16.0.0/12"
}
output "vpc_id" {
  value = "${alicloud_vpc.vpc.id}"
}