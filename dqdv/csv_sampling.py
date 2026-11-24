"""Export regularly spaced records from a raw CSV."""

import codecs
import csv
from pathlib import Path
from tempfile import NamedTemporaryFile


def sample_csv(source, output, start_row, interval):
    """Keep the header and records at start_row + n * interval (header is row 1)."""
    source, output = Path(source), Path(output)
    if start_row < 2 or interval < 1:
        raise ValueError('시작 행은 2 이상, 저장 간격은 1 이상이어야 합니다.')
    if source.resolve() == output.resolve():
        raise ValueError('원본과 다른 파일명으로 저장하세요.')

    with source.open('rb') as raw:
        bom = raw.read(2)
    encodings = ('utf-16',) if bom in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE) else ('utf-8-sig', 'cp949')

    for encoding in encodings:
        temporary_path = None
        try:
            with source.open(encoding=encoding, newline='') as original, NamedTemporaryFile(
                mode='w', encoding='utf-8-sig', newline='', dir=output.parent, delete=False
            ) as target:
                temporary_path = Path(target.name)
                reader = csv.reader(original, strict=True)
                header = next(reader, None)
                if not header:
                    raise ValueError('CSV의 첫 행에 열 제목이 필요합니다.')
                writer = csv.writer(target)
                writer.writerow(header)
                saved_rows = 0
                for row_number, row in enumerate(reader, start=2):
                    if row_number >= start_row and (row_number - start_row) % interval == 0:
                        writer.writerow(row)
                        saved_rows += 1
                if not saved_rows:
                    raise ValueError('시작 행이 CSV의 마지막 행보다 큽니다.')
            temporary_path.replace(output)
            return saved_rows
        except UnicodeDecodeError:
            continue
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    raise ValueError('CSV 인코딩을 읽을 수 없습니다. UTF-8, CP949, UTF-16을 지원합니다.')
