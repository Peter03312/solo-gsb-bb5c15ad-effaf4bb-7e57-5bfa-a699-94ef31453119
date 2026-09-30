"""精确小数计算工具：金额/体积类计算统一使用 Decimal。"""
from decimal import Decimal, ROUND_HALF_UP

from .config import CONC_DECIMALS, VOLUME_DECIMALS

_VOL_Q = Decimal(1).scaleb(-VOLUME_DECIMALS)  # 0.0001
_CONC_Q = Decimal(1).scaleb(-CONC_DECIMALS)


def q_volume(value) -> Decimal:
    """把取液量/体积量化到 4 位小数（四舍五入）。"""
    return Decimal(str(value)).quantize(_VOL_Q, rounding=ROUND_HALF_UP)


def q_conc(value) -> Decimal:
    """把浓度量化到 6 位小数。"""
    return Decimal(str(value)).quantize(_CONC_Q, rounding=ROUND_HALF_UP)


def take_volume(target_dose: Decimal, concentration: Decimal) -> Decimal:
    """取液量 = 投料量 ÷ 浓度，结果按 4 位小数四舍五入。"""
    return q_volume(target_dose / concentration)


def to_scaled_int(value: Decimal) -> int:
    """把 4 位小数的体积转为整数（×10^VOLUME_DECIMALS），供 CP-SAT 使用。"""
    return int(q_volume(value) * (10 ** VOLUME_DECIMALS))
