"""
CMW500 自动化测试工具 - 仪器连接模块

功能说明：
    封装 CMW500 仪器的连接、断开、信息查询等操作。
    支持三种接口方式：
      - LAN（TCP/IP）：通过网线直连，需指定 IP 地址
      - GPIB（IEEE-488）：通过 GPIB 线缆连接，需指定板号和主地址
      - USB（TMC）：通过 USB 线直连，需指定 VID/PID/序列号

SCPI 指令参考：
    *IDN?  —— 查询仪器标识信息（制造商、型号、序列号、固件版本）
"""

import pyvisa


class CMW500Connection:
    """CMW500 仪器连接管理类（支持 LAN / GPIB / USB 三种接口）"""

    # 支持的接口类型常量
    INTERFACE_LAN = "LAN"
    INTERFACE_GPIB = "GPIB"
    INTERFACE_USB = "USB"

    def __init__(self, interface_type="LAN", lan_ip="", gpib_board=0,
                 gpib_address=20, usb_vendor_id="0x0AAD",
                 usb_product_id="0x0117", usb_serial_number="",
                 timeout=10000):
        """
        初始化连接管理器（不立即连接）

        参数:
            interface_type:    接口类型，"LAN"、"GPIB" 或 "USB"
            lan_ip:            LAN 模式下的 IP 地址（字符串）
            gpib_board:        GPIB 模式下的板号（整数，通常 0）
            gpib_address:      GPIB 模式下的主地址（整数，通常 0~30）
            usb_vendor_id:     USB 模式下的厂商标识 VID（如 "0x0AAD"）
            usb_product_id:    USB 模式下的产品标识 PID（如 "0x0117"）
            usb_serial_number: USB 模式下的仪器序列号（留空则自动搜索）
            timeout:           通信超时时间，单位毫秒，默认 10000ms
        """
        self.interface_type = interface_type
        self.lan_ip = lan_ip
        self.gpib_board = gpib_board
        self.gpib_address = gpib_address
        self.usb_vendor_id = usb_vendor_id
        self.usb_product_id = usb_product_id
        self.usb_serial_number = usb_serial_number
        self.timeout = timeout
        self.resource_manager = None  # VISA 资源管理器
        self.instrument = None        # 仪器连接实例
        self.connected = False        # 连接状态标志

    def _build_resource_address(self):
        """
        根据当前接口类型构造 VISA 资源地址字符串

        返回:
            str: VISA 资源地址
        """
        if self.interface_type == self.INTERFACE_GPIB:
            # GPIB 格式：GPIB<board>::<address>::INSTR
            return f"GPIB{self.gpib_board}::{self.gpib_address}::INSTR"

        elif self.interface_type == self.INTERFACE_USB:
            # USB 格式：USB0::<VID>::<PID>::<serial>::INSTR
            # 如果序列号为空，使用通配符 ? 让 VISA 自动匹配第一个设备
            serial_part = self.usb_serial_number if self.usb_serial_number else "?"
            return f"USB0::{self.usb_vendor_id}::{self.usb_product_id}::{serial_part}::INSTR"

        else:
            # LAN 格式：TCPIP0::<IP地址>::inst0::INSTR
            return f"TCPIP0::{self.lan_ip}::inst0::INSTR"

    def _get_interface_name(self):
        """获取当前接口类型的中文名称"""
        names = {
            self.INTERFACE_LAN: "LAN (TCP/IP)",
            self.INTERFACE_GPIB: "GPIB (IEEE-488)",
            self.INTERFACE_USB: "USB (TMC)",
        }
        return names.get(self.interface_type, self.interface_type)

    def connect(self):
        """
        建立与 CMW500 的连接（根据接口类型自动选择 LAN / GPIB / USB）

        返回:
            (bool, str): 元组 —— (是否成功, 提示信息)
        """
        try:
            # 创建 VISA 资源管理器
            self.resource_manager = pyvisa.ResourceManager()

            # 构造资源地址字符串
            resource_address = self._build_resource_address()

            # 打开仪器连接
            self.instrument = self.resource_manager.open_resource(resource_address)

            # 设置通信超时
            self.instrument.timeout = self.timeout

            # 尝试查询仪器标识，验证连接是否有效
            idn = self.instrument.query("*IDN?").strip()

            self.connected = True
            interface_name = self._get_interface_name()
            return True, f"通过 {interface_name} 连接成功！\n仪器信息：{idn}"

        except pyvisa.VisaIOError as e:
            # VISA 通信层错误（如网络不通、地址错误）
            self.connected = False
            if self.interface_type == self.INTERFACE_GPIB:
                hint = (f"GPIB 地址：Board={self.gpib_board}, "
                        f"Address={self.gpib_address}\n"
                        f"请检查 GPIB 线缆连接和地址设置是否正确。")
            elif self.interface_type == self.INTERFACE_USB:
                hint = (f"USB 参数：VID={self.usb_vendor_id}, "
                        f"PID={self.usb_product_id}, "
                        f"SN={self.usb_serial_number or '(自动搜索)'}\n"
                        f"请检查 USB 线缆是否已连接，驱动是否已安装。")
            else:
                hint = (f"IP 地址：{self.lan_ip}\n"
                        f"请检查网络线缆连接和 IP 地址是否正确。")
            return False, f"连接失败：无法与仪器通信。\n{hint}\n详细信息：{e}"

        except Exception as e:
            # 其他未知错误
            self.connected = False
            return False, f"连接失败：发生未知错误。\n详细信息：{e}"

    def disconnect(self):
        """
        断开与 CMW500 的连接

        返回:
            (bool, str): 元组 —— (是否成功, 提示信息)
        """
        if not self.connected or self.instrument is None:
            return False, "当前未连接任何仪器，无需断开"

        try:
            # 关闭仪器连接
            self.instrument.close()
            self.instrument = None
            self.connected = False
            return True, "已成功断开仪器连接"

        except pyvisa.VisaIOError as e:
            self.connected = False
            self.instrument = None
            return False, f"断开连接时出错：{e}"

        except Exception as e:
            self.connected = False
            self.instrument = None
            return False, f"断开连接时发生未知错误：{e}"

    def get_serial_number(self):
        """
        读取仪器序列号

        通过 *IDN? 指令获取仪器标识字符串，从中解析出序列号。
        返回格式：制造商,型号,序列号,固件版本

        返回:
            (bool, str): 元组 —— (是否成功, 序列号或错误信息)
        """
        if not self.connected or self.instrument is None:
            return False, "未连接仪器，无法读取序列号"

        try:
            # 发送 *IDN? 查询指令
            idn = self.instrument.query("*IDN?").strip()

            # 解析返回字符串（格式：制造商,型号,序列号,版本号）
            parts = idn.split(",")
            if len(parts) >= 3:
                serial_number = parts[2].strip()
                return True, serial_number
            else:
                return False, f"仪器返回格式异常：{idn}"

        except pyvisa.VisaIOError as e:
            return False, f"读取序列号失败（通信错误）：{e}"

        except Exception as e:
            return False, f"读取序列号失败：{e}"

    def send_command(self, command):
        """
        向仪器发送 SCPI 命令（无返回值）

        参数:
            command: SCPI 命令字符串
        """
        if not self.connected or self.instrument is None:
            raise ConnectionError("仪器未连接，无法发送命令")
        self.instrument.write(command)

    def query(self, command):
        """
        向仪器发送查询命令并返回结果

        参数:
            command: SCPI 查询命令字符串

        返回:
            仪器返回的字符串（已去除首尾空白）
        """
        if not self.connected or self.instrument is None:
            raise ConnectionError("仪器未连接，无法执行查询")
        return self.instrument.query(command).strip()
