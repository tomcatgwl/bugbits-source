"""模拟核心包（T4.4a 起）。D4: 本包禁 import render/，自身不做 IO——
全部输入（level/world/units）由调用方装载后注入。20Hz工程tick，R367蜜独立子步/LCG
作为明确状态保存；不宣称原作所有时钟和随机流已经还原。"""
from bugbits.sim import consts
from bugbits.sim.entities import Bug, Flower, Hive, NectarItem
from bugbits.sim.sim import Sim

__all__ = ["consts", "Sim", "Bug", "Flower", "Hive", "NectarItem"]
