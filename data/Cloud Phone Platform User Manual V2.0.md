# Nebula Cloud Phone Platform User Manual V2.0

## 1. Platform Overview
Nebula Cloud Phone is a PaaS/SaaS product based on ARM server architecture and cloud virtualization technology. It migrates the computing power, storage, and network capabilities of physical smartphones to the cloud, providing users with complete virtual Android phone services. Users can control cloud phones in real-time via video streaming using PCs, web browsers, or local thin clients. This platform is widely used in scenarios such as cloud gaming, mobile office work, automated testing, APP group control for marketing, live streaming entertainment, and data compliance storage.

## 2. Core Features
- **Elastic Computing & Multi-Spec Support**: Provides various computing specifications ranging from Basic (2 Cores, 4GB RAM) to Flagship (8 Cores, 16GB RAM), supporting multiple OS versions from Android 9 to Android 13 to meet diverse performance requirements.
- **Large-Scale Group Control**: Supports managing tens of thousands of cloud phone instances under a single account. Features include screen synchronization, command synchronization, and batch file distribution, significantly improving O&M efficiency.
- **Custom Images & Pre-installation**: Allows users to create "Custom Images" from configured cloud phones and apply them directly during subsequent batch instance creation, achieving second-level business deployment.
- **Open API & SDK**: Provides comprehensive RESTful APIs and Java/Python SDKs, enabling seamless integration with existing enterprise systems (e.g., OA, CRM, automated testing platforms).
- **Endpoint-Cloud Collaboration & Peripheral Mapping**: Supports mapping physical peripherals of local devices, such as GPS, cameras, microphones, and gravity sensors, to the cloud phone for seamless endpoint-cloud collaboration.

## 3. Quick Start Guide
### 3.1 Registration & Real-Name Authentication
Visit the official Nebula Cloud Phone website and register using a phone number or corporate email. In compliance with national regulations, users must complete personal or enterprise real-name authentication before using the cloud services. Once authenticated, cloud services can be activated.

### 3.2 Purchasing Cloud Phone Instances
1. Log in to the console, navigate to the "Cloud Phone Management" page, and click "Purchase Instance".
2. Select the region and availability zone (it is recommended to choose a region close to target users or business servers to minimize latency).
3. Choose the instance specifications (CPU, RAM, storage capacity) and OS version.
4. Configure network settings (bind an Elastic IP or connect to an enterprise VPC private network).
5. Confirm the order and complete the payment.

### 3.3 Logging into the Console
After purchase, you can view the created cloud phones in the "Instance List". Click "Manage" to enter the detailed console for a specific cloud phone.

## 4. Core Operations Manual
### 4.1 Connection & Screen Casting
- **Web Connection**: Click "Connect" in the console. The browser will open the cloud phone screen directly via the WebRTC protocol, supporting smooth control without plugins.
- **Client Connection**: Download the Nebula Cloud Phone PC client, log in by scanning a QR code or entering the Instance ID. It supports multi-window split-screen display and HD picture quality adjustment.
- **ADB Debugging**: Enable the "ADB Debugging" switch for the instance, obtain the public IP and port, and use local ADB tools to connect via the command `adb connect IP:Port` for command-line debugging.

### 4.2 App & File Management
- **App Installation**: Select "App Management" from the left menu in the console. You can upload local APK files or install apps directly from the official app store. In group control mode, APKs can be pushed to multiple instances in batches.
- **File Transfer**: Through the "File Management" module, you can upload local images, documents, and archives to the virtual SD card of the cloud phone. You can also package and download files from the cloud phone to your local machine.
- **Cloud Disk Mounting**: Supports mounting shared cloud disks to enable data interoperability and sharing among multiple cloud phones.

### 4.3 Instance Lifecycle Management
- **Power On/Off/Restart**: Check the target cloud phones in the instance list and click the top action bar for power management.
- **System Reset**: If the system encounters anomalies or needs data clearing, select "Reset". The system will revert to the initial image state (Note: This operation will erase all system disk data).
- **Release Instance**: For subscription or pay-as-you-go instances no longer in use, execute the "Release" operation to stop billing and destroy data.

## 5. Advanced Features
### 5.1 Automation Scripts & Group Control
The platform has a built-in "Automation Tasks" module. Users can generate scripts by recording screen operations or write Python/JS scripts to execute on cloud phones. In group control scenarios, you can set up "Master-Slave Synchronization," where operating the master cloud phone will synchronize all clicks, swipes, and inputs across all slave cloud phones in real-time.

### 5.2 Image Management
1. **Create Image**: Select a cloud phone with a configured business environment, click "Create Custom Image," and enter the image name and description.
2. **Image Sharing & Copying**: Custom images can be shared to other regions under the same account or cross-account to sub-accounts, enabling rapid cross-region business deployment.

### 5.3 API Integration
Developers can automate the orchestration of cloud phone resources via APIs. Common interfaces include:
- `CreateCloudPhone`: Batch create cloud phone instances.
- `RunCommand`: Issue Shell commands or execute automation scripts to cloud phones.
- `PushFile`: Push files to specified directories on cloud phones via API.
Before calling, obtain the AccessKey and SecretKey from the console for signature authentication.

## 6. Frequently Asked Questions (FAQ)
**Q1: What should I do if the screen casting is laggy or has high latency?**
A: Screen latency is usually affected by the network environment. Please check your local network bandwidth. It is recommended to lower the picture quality and frame rate (e.g., from 60fps to 30fps) in the console's "Connection Settings," or switch to H.265 encoding to reduce bandwidth usage. If using a public IP, it is advised to deploy the cloud phones and business servers within the same regional VPC intranet.

**Q2: How to get real GPS location inside the cloud phone?**
A: By default, cloud phones use base stations or IPs for simulated positioning. If your business requires real positioning, please enable the "Location Simulation" feature in the console, manually input latitude and longitude via API or console, or use the endpoint-cloud collaboration feature to map the GPS signal of a local physical phone.

**Q3: How to back up data inside the cloud phone?**
A: The cloud phone provides a "Data Backup" feature, allowing you to create snapshots for both the system disk and data disk. Snapshots can be used for subsequent data recovery or creating new images. It is recommended to configure scheduled automatic backup policies for core business data.

**Q4: Do cloud phones support ROOT permissions?**
A: To ensure system stability and security, standard cloud phones do not provide ROOT permissions by default. If enterprises have special underlying debugging needs, they can select the "Developer Version" during purchase or apply for ROOT permission in the console (requires signing a security commitment letter).

## 7. Security and Compliance Statement
The Nebula Cloud Phone platform strictly complies with national Cybersecurity Law and Data Security Law.
- **Data Privacy**: User data is encrypted and stored in the cloud using AES-256. The platform commits to not touching or leaking any user business data. After an instance is released, the underlying physical storage will be overwritten and destroyed multiple times.
- **Usage Regulations**: It is strictly prohibited to use this platform for telecom network fraud, black/gray market group control, malicious traffic brushing, intellectual property infringement, and other illegal activities. The platform is equipped with an AI risk control system; once illegal operations are detected, instances will be frozen immediately and reported to public security organs.