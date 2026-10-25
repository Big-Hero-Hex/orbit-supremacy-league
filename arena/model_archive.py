"""Inspect SB3 ZIP structure without importing or executing participant code."""
import json
import zipfile

VERSION = 1


def validate_archive(path):
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            missing = sorted({'data', 'policy.pth'} - names)
            if missing:
                raise ValueError('缺少 ' + '、'.join(missing) + '；請直接上傳訓練儲存的 SB3 模型 ZIP，不是報告或外層作業壓縮檔')
            info = archive.getinfo('data')
            if info.file_size > 16 * 1024 * 1024:
                raise ValueError('模型 data 超過可驗證大小')
            if not isinstance(json.loads(archive.read('data')), dict):
                raise ValueError('模型 data 必須是 SB3 JSON 物件')
            if archive.getinfo('policy.pth').file_size == 0:
                raise ValueError('policy.pth 是空檔')
        return {'version': VERSION, 'status': 'valid', 'scope': 'ZIP structure only; isolated runtime loading still required'}
    except (ValueError, KeyError, OSError, RuntimeError, zipfile.BadZipFile, UnicodeError) as exc:
        return {'version': VERSION, 'status': 'invalid', 'message': '不是可用的模型 ZIP：' + str(exc)[:350]}
