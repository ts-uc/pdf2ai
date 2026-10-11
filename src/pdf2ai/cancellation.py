"""Cooperative cancellation at safe conversion boundaries."""


class ConversionCancelled(RuntimeError):
    pass


def check_cancelled(callback):
    if callback is not None and callback():
        raise ConversionCancelled('変換をキャンセルしました。未保存の出力は公開しません。')
