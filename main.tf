# ==========================================
# TERRAFORM CONFIGURATION & PROVIDERS
# ==========================================

terraform {
  required_version = ">= 1.0.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

# 1. AWS Provider Configuration (Frankfurt)
provider "aws" {
  region = "eu-central-1"
}


# 2. Azure Provider Configuration (Spain)
provider "azurerm" {
  features {}
}

# 3. GCP Provider Configuration (Frankfurt)
provider "google" {
  project = "quick-hangout-477408-g8"
  region  = "europe-west3"
  zone    = "europe-west3-a"
}

# ==========================================
# 1. AWS INFRASTRUCTURE (t3.micro Free Tier)
# ==========================================

resource "aws_vpc" "testbed_vpc" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  tags                 = { Name = "testbed-vpc" }
}

resource "aws_subnet" "testbed_subnet" {
  vpc_id                  = aws_vpc.testbed_vpc.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = "eu-central-1a"
  map_public_ip_on_launch = true
}

resource "aws_internet_gateway" "testbed_igw" {
  vpc_id = aws_vpc.testbed_vpc.id
}

resource "aws_route_table" "testbed_rt" {
  vpc_id = aws_vpc.testbed_vpc.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.testbed_igw.id
  }
}

resource "aws_route_table_association" "testbed_rta" {
  subnet_id      = aws_subnet.testbed_subnet.id
  route_table_id = aws_route_table.testbed_rt.id
}

resource "aws_security_group" "aws_testbed_sg" {
  name   = "aws-testbed-sg"
  vpc_id = aws_vpc.testbed_vpc.id

  # HTTP access for JMeter Load Testing
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # SSH access for setup
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # ICMP (Ping) access for Latency Scripts
  ingress {
    from_port   = -1
    to_port     = -1
    protocol    = "icmp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "aws_free_vm" {
  ami                    = "ami-0084a47cc718c111a" # Ubuntu 22.04 LTS Server AMI for eu-central-1
  instance_type          = "t3.micro"              # AWS Free Tier eligible
  subnet_id              = aws_subnet.testbed_subnet.id
  vpc_security_group_ids = [aws_security_group.aws_testbed_sg.id]

  user_data = <<-EOF
              #!/bin/bash
              apt-get update
              apt-get install -y apache2
              echo "Hello World from AWS Frankfurt" > /var/www/html/index.html
              EOF

  tags = { Name = "Testbed-AWS" }
}


# ==========================================
# 2. MICROSOFT AZURE INFRASTRUCTURE (Standard_B2s_v2 Free Tier)
# ==========================================

resource "azurerm_resource_group" "testbed_rg" {
  name     = "testbed-resources"
  location = "spaincentral"
}

resource "azurerm_virtual_network" "testbed_vnet" {
  name                = "testbed-vnet"
  address_space       = ["10.0.0.0/16"]
  location            = azurerm_resource_group.testbed_rg.location
  resource_group_name = azurerm_resource_group.testbed_rg.name
}

resource "azurerm_subnet" "testbed_subnet" {
  name                 = "testbed-subnet"
  resource_group_name  = azurerm_resource_group.testbed_rg.name
  virtual_network_name = azurerm_virtual_network.testbed_vnet.name
  address_prefixes     = ["10.0.1.0/24"]
}

resource "azurerm_public_ip" "azure_pip" {
  name                = "azure-vm-pip"
  location            = azurerm_resource_group.testbed_rg.location
  resource_group_name = azurerm_resource_group.testbed_rg.name
  allocation_method   = "Static"
  sku                 = "Standard"
}

resource "azurerm_network_security_group" "azure_nsg" {
  name                = "azure-testbed-nsg"
  location            = azurerm_resource_group.testbed_rg.location
  resource_group_name = azurerm_resource_group.testbed_rg.name

  security_rule {
    name                       = "allow-http"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "80"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "allow-ssh"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "allow-icmp"
    priority                   = 120
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Icmp"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_network_interface" "azure_nic" {
  name                = "azure-vm-nic"
  location            = azurerm_resource_group.testbed_rg.location
  resource_group_name = azurerm_resource_group.testbed_rg.name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.testbed_subnet.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.azure_pip.id
  }
}

resource "azurerm_network_interface_security_group_association" "azure_nic_sg" {
  network_interface_id      = azurerm_network_interface.azure_nic.id
  network_security_group_id = azurerm_network_security_group.azure_nsg.id
}

resource "azurerm_linux_virtual_machine" "azure_free_vm" {
  name                = "Testbed-Azure"
  resource_group_name = azurerm_resource_group.testbed_rg.name
  location            = azurerm_resource_group.testbed_rg.location
  size                = "Standard_B2s_v2"
  admin_username      = "azureuser"

  disable_password_authentication = false
  admin_password                  = var.azure_admin_password

  network_interface_ids = [
    azurerm_network_interface.azure_nic.id,
  ]

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }

  custom_data = base64encode(<<-EOF
                #!/bin/bash
                apt-get update
                apt-get install -y apache2
                echo "Hello World from Azure Spain" > /var/www/html/index.html
                EOF
  )
}

# ==========================================
# 3. GCP INFRASTRUCTURE (e2-micro Free Tier)
# ==========================================

resource "google_compute_network" "testbed_vpc" {
  name                    = "gcp-testbed-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "testbed_subnet" {
  name          = "gcp-testbed-subnet"
  ip_cidr_range = "10.2.1.0/24"
  region        = "europe-west3"
  network       = google_compute_network.testbed_vpc.id
}

resource "google_compute_firewall" "gcp_firewall" {
  name    = "gcp-testbed-firewall"
  network = google_compute_network.testbed_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["22", "80"]
  }

  allow {
    protocol = "icmp"
  }

  source_ranges = ["0.0.0.0/0"]

  target_tags = ["http-server"]
}

resource "google_compute_instance" "gcp_free_vm" {
  name         = "testbed-gcp"
  machine_type = "e2-micro"
  zone         = "europe-west3-a"

  tags = ["http-server"]

  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2204-lts"
    }
  }

  network_interface {
    network    = google_compute_network.testbed_vpc.id
    subnetwork = google_compute_subnetwork.testbed_subnet.id

    access_config {
    }
  }

  metadata_startup_script = <<EOF
#!/bin/bash
apt-get update
apt-get install -y apache2
echo "Hello World from GCP Frankfurt" > /var/www/html/index.html
EOF
}


# ==========================================
# OUTPUTS
# ==========================================

output "aws_public_ip" {
  value       = aws_instance.aws_free_vm.public_ip
  description = "Public IP of AWS Instance"
}

output "azure_public_ip" {
  value       = azurerm_linux_virtual_machine.azure_free_vm.public_ip_address
  description = "Public IP of Azure Instance"
}

output "gcp_public_ip" {
  value       = google_compute_instance.gcp_free_vm.network_interface[0].access_config[0].nat_ip
  description = "Public IP of GCP Instance"
}

