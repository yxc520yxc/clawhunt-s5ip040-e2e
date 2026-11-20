"""虚构夹具：全部为假数据，无真实个人信息，交付物不含客户名称。"""
from __future__ import annotations

FICTIONAL_TITLES = [
    "虚构节目 · 会员中台如何连接产业资源",
    "虚构节目 · 从场地运营到数据平台",
]

FICTIONAL_GUESTS = ["虚构嘉宾甲", "虚构嘉宾乙"]


def make_project_payload(idx: int = 0, **overrides):
    payload = {"title": FICTIONAL_TITLES[idx % len(FICTIONAL_TITLES)],
               "transcribe_fail": False, "keep_pending": False}
    payload.update(overrides)
    return payload


def make_auth_payload(idx: int = 0):
    return {"guest_name": FICTIONAL_GUESTS[idx % len(FICTIONAL_GUESTS)]}
