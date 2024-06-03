"""工具类"""
import base64
import random
import string
import time
from io import BytesIO
from typing import Type
from urllib.parse import parse_qsl, urlparse

import qrcode
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding, serialization
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from pydantic import ValidationError
from tenacity import RetryError, Retrying, stop_after_attempt

from .captcha import get_validate_by_2captcha, get_validate_by_eee
from .data_model import TokenResultHandler
from .logger import log
from .request import post

import importlib
import subprocess
import importlib
import sys

package = '2CAPTCHA-Python'
import_as = 'twocaptcha'
# wrong_package = 'twocaptcha'

try:
    importlib.import_module(import_as)
except ImportError:
    print(f"没有找到 {import_as} 包，正在尝试安装 {package} ...")
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
    print(f"{package} 安装成功！")

from twocaptcha import TwoCaptcha

if not hasattr(TwoCaptcha, "geetest"):
    print(f"检测到已安装错误的 {import_as} 包，正在尝试卸载并安装 {package} ...")
    subprocess.check_call([sys.executable, '-m', 'pip', 'uninstall', '-y', import_as])
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
    print(f"{package} 安装成功！正在尝试重新加载正确的依赖包")
    importlib.invalidate_caches()
    del sys.modules[import_as]
    importlib.import_module(import_as)
    from twocaptcha import TwoCaptcha
    if not hasattr(TwoCaptcha, "geetest"):
        print(f"尝试加载正确的 {import_as} 包失败，请重新运行脚本，暂不需要做任何其它处理")
        exit(1)
    else:
        print(f"成功重新加载正确的 {import_as} 包，脚本继续运行")
else:
    print(f"检测到已安装正确的 {import_as} 包，脚本继续运行")

from .config import ConfigManager
_conf = ConfigManager.data_obj

PUBLIC_KEY_PEM = '''-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEArxfNLkuAQ/BYHzkzVwtu
g+0abmYRBVCEScSzGxJIOsfxVzcuqaKO87H2o2wBcacD3bRHhMjTkhSEqxPjQ/FE
XuJ1cdbmr3+b3EQR6wf/cYcMx2468/QyVoQ7BADLSPecQhtgGOllkC+cLYN6Md34
Uii6U+VJf0p0q/saxUTZvhR2ka9fqJ4+6C6cOghIecjMYQNHIaNW+eSKunfFsXVU
+QfMD0q2EM9wo20aLnos24yDzRjh9HJc6xfr37jRlv1/boG/EABMG9FnTm35xWrV
R0nw3cpYF7GZg13QicS/ZwEsSd4HyboAruMxJBPvK3Jdr4ZS23bpN0cavWOJsBqZ
VwIDAQAB
-----END PUBLIC KEY-----'''

headers = {
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Content-type': 'application/x-www-form-urlencoded',
    'Origin': 'https://web.vip.miui.com',
    'Pragma': 'no-cache',
    'Referer': 'https://web.vip.miui.com/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'cross-site',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0',
    'sec-ch-ua': '"Microsoft Edge";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
}

def get_random_chars_as_string(length, characters: str = string.ascii_letters + string.digits + string.punctuation):
    """获取随机字符串"""
    return ''.join(random.choice(characters) for _ in range(length))

def aes_encrypt(key: str, data: str) -> base64:
    """AES加密"""
    iv = b'0102030405060708'  # pylint: disable=invalid-name
    cipher = Cipher(algorithms.AES(key.encode('utf-8')), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded_data = padder.update(data.encode('utf-8')) + padder.finalize()
    ciphertext = encryptor.update(padded_data) + encryptor.finalize()
    return base64.b64encode(ciphertext).decode('utf-8')


def rsa_encrypt(public_key_pem: str, data: str) -> base64:
    """RSA加密"""
    public_key = serialization.load_pem_public_key(
        public_key_pem.encode('utf-8'),
        backend=default_backend()
    )
    encoded_data = base64.b64encode(data.encode('utf-8'))
    ciphertext = public_key.encrypt(
        encoded_data,
        PKCS1v15()
    )

    return base64.b64encode(ciphertext).decode('utf-8')


IncorrectReturn = (KeyError, TypeError, AttributeError, IndexError, ValidationError)
"""API返回数据无效会触发的异常组合"""


def is_incorrect_return(exception: Exception, *addition_exceptions: Type[Exception]) -> bool:
    """
    判断是否是API返回数据无效的异常
    :param exception: 异常对象
    :param addition_exceptions: 额外的异常类型，用于触发判断
    """
    exceptions = IncorrectReturn + addition_exceptions
    return isinstance(exception, exceptions) or isinstance(exception.__cause__, exceptions)


async def get_token_by_captcha(url: str,use_2captcha: bool) -> str | bool:
    """通过人机验证码获取TOKEN"""
    try:
        parsed_url = urlparse(url)
        query_params = dict(parse_qsl(parsed_url.query))  # 解析URL参数
        gt = query_params.get("c")  # pylint: disable=invalid-name
        challenge = query_params.get("l")
        if use_2captcha:
            log.info("尝试使用2captcha获取token，使用server："+str(_conf.preference.twocaptcha_server))
            solver = TwoCaptcha(apiKey=_conf.preference.twocaptcha_api_key,server=_conf.preference.twocaptcha_server)
            geetest_data = await get_validate_by_2captcha(gt, challenge ,url)
        else:
            log.info("尝试使用eee的打码平台获取token，使用server："+str(_conf.preference.geetest_url))
            geetest_data = await get_validate_by_eee(gt, challenge)
        params = {
            'k': '3dc42a135a8d45118034d1ab68213073',
            'locale': 'zh_CN',
            '_t': round(time.time() * 1000),
        }

        data = {
            'e': query_params.get("e"),  # 人机验证的e参数，来自URL
            'challenge': geetest_data.challenge,
            'seccode': f'{geetest_data.validate}|jordan',
        }

        response = await post('https://verify.sec.xiaomi.com/captcha/v2/gt/dk/verify', params=params, headers=headers,
                              data=data)
        log.debug(response.text)
        result = response.json()
        api_data = TokenResultHandler(result)
        if api_data.success:
            if use_2captcha:
                try:
                    solver.report(geetest_data.taskId,True)
                    log.success("成功使用2captcha获取token并反馈")
                except Exception:
                    pass
            else:
                log.success("使用eee的打码平台成功获取token")
            return api_data.token
        elif not api_data.data.get("result"):
            log.error("遇到人机验证码，无法获取TOKEN")
            log.debug("接口返回："+str(response.text))
            if use_2captcha:
                if geetest_data.taskId:
                    try:
                        solver.report(geetest_data.taskId,False)
                        log.info("已向2captcha反馈失败情况")
                    except Exception:
                        pass
                else:
                    log.error("没有获取到2captcha的taskId，跳过上报错误")
            else:
                log.info("使用eee的打码平台获取token失败")
            return False
        else:
            log.error("遇到未知错误，无法获取TOKEN")
            log.debug("接口返回："+str(response.text))
            if use_2captcha :
                if geetest_data.taskId:
                    try:
                        solver.report(geetest_data.taskId,False)
                        log.info("已向2captcha反馈失败情况")
                    except Exception:
                        pass
                else:
                    log.error("没有获取到2captcha的taskId，跳过上报错误")
            else:
                log.info("使用eee的打码平台获取token失败")
            return False
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception("获取TOKEN异常")
        return False


# pylint: disable=trailing-whitespace
async def get_token(uid: str) -> str | bool:
    """获取TOKEN"""
    try:
        counter = 0
        for attempt in Retrying(stop=stop_after_attempt(6)):
            with attempt:
                counter += 1
                # use_2captcha为true时使用2captcha
                use_2captcha = counter <= 3
                # use_2captcha = counter > 3
                log.info("第"+str(counter)+"次尝试")
                data = {
                    "type": 0,
                    "startTs": round(time.time() * 1000),
                    "endTs": round(time.time() * 1000),
                    "env": {
                        "p1": "",
                        "p2": "",
                        "p3": "",
                        "p4": "",
                        "p5": "",
                        "p6": "",
                        "p7": "",
                        "p8": "",
                        "p9": "",
                        "p10": "",
                        "p11": "",
                        "p12": "",
                        "p13": "",
                        "p14": "",
                        "p15": "",
                        "p16": "",
                        "p17": "",
                        "p18": "",
                        "p19": "",
                        "p20": "",
                        "p21": "",
                        "p22": "",
                        "p23": "",
                        "p24": "",
                        "p25": "",
                        "p26": "",
                        "p28": "",
                        "p29": "",
                        "p30": "",
                        "p31": "",
                        "p32": "",
                        "p33": [],
                        "p34": ""
                    },
                    "action": {
                        "a1": [],
                        "a2": [],
                        "a3": [],
                        "a4": [],
                        "a5": [],
                        "a6": [],
                        "a7": [],
                        "a8": [],
                        "a9": [],
                        "a10": [],
                        "a11": [],
                        "a12": [],
                        "a13": [],
                        "a14": []
                    },
                    "force": False,
                    "talkBack": False,
                    "uid": uid,
                    "nonce": {
                        "t": round(time.time()),
                        "r": round(time.time())
                    },
                    "version": "2.0",
                    "scene": "GROW_UP_CHECKIN"
                }

                key = get_random_chars_as_string(16)

                params = {
                    'k': '3dc42a135a8d45118034d1ab68213073',
                    'locale': 'zh_CN',
                    '_t': round(time.time() * 1000),
                }

                data = {
                    's': rsa_encrypt(PUBLIC_KEY_PEM, key),
                    'd': aes_encrypt(key, str(data)),
                    'a': 'GROW_UP_CHECKIN',
                }
                response = await post('https://verify.sec.xiaomi.com/captcha/v2/data', params=params, headers=headers,
                                      data=data)
                log.debug(response.text)
                result = response.json()
                api_data = TokenResultHandler(result)
                if api_data.success:
                    return api_data.token
                elif api_data.need_verify:
                    log.error("遇到人机验证码, 尝试调用解决方案")
                    url = api_data.data.get("url")
                    if token := await get_token_by_captcha(url,use_2captcha):
                        return token
                    else:
                        raise ValueError("人机验证失败")
                else:
                    log.error("遇到未知错误，无法获取TOKEN")
                    return False
    except RetryError as error:
        if is_incorrect_return(error):
            log.exception(f"TOKEN - 服务器没有正确返回 {response.text}")
        else:
            log.exception("获取TOKEN异常")
        return False

def generate_qrcode(url):
    """生成二维码"""
    qr = qrcode.QRCode(version=1, # pylint: disable=invalid-name
                       error_correction=qrcode.constants.ERROR_CORRECT_L,
                       box_size=10,
                       border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    bio = BytesIO()
    img.save(bio)
    # 获取二维码的模块 (module) 列表
    qr_modules = qr.get_matrix()
    chaes = ["  ", "██"]
    # 在控制台中打印二维码
    for row in qr_modules:
        line = "".join(chaes[pixel] for pixel in row)
        print(line)
        log.debug(line)
        