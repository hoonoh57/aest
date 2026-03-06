"""
클립보드 텍스트 파싱 — HTS 1516 성과검증 복사 데이터

실제 형식 (탭 구분):
  종목명  1분수익률  3분수익률  7시간수익률  최고수익률  거래량  기타
  헥토파이낸셜  "-1.93%"  "-2.46%"  "+15.79%"  "+15.79%"  "246,429"  "-1.93"
"""

import re
from typing import List, Dict


class ClipboardParser:

    def parse(self, raw_text: str) -> List[Dict]:
        lines = raw_text.strip().split("\n")
        results = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            # 헤더 스킵
            if "종목명" in line or "1분간" in line or "기간" in line:
                continue

            cols = re.split(r'\t+', line)
            # 앞에 빈 탭이 있을 수 있으므로 제거
            cols = [c.strip() for c in cols if c.strip()]

            if len(cols) < 5:
                continue

            name = cols[0].strip()

            # 형식: 종목명, 1분, 3분, 7시간, 최고, 거래량 [, 기타]
            if len(cols) >= 6:
                ret_1m = self._parse_pct(cols[1])
                ret_3m = self._parse_pct(cols[2])
                ret_7h = self._parse_pct(cols[3])
                max_ret = self._parse_pct(cols[4])
                vol = self._parse_int(cols[5])
            elif len(cols) == 5:
                ret_1m = None
                ret_3m = None
                ret_7h = self._parse_pct(cols[1])
                max_ret = self._parse_pct(cols[2])
                vol = self._parse_int(cols[3])
            else:
                continue

            results.append({
                "name": name,
                "return_1m": ret_1m,
                "return_3m": ret_3m,
                "return_7h": ret_7h,
                "max_return": max_ret,
                "volume_krw": vol,
                "raw_text": line,
            })

        return results

    def _parse_pct(self, s: str):
        if s is None:
            return None
        try:
            # ""-1.93%"" or "+15.79%" or "0%"
            cleaned = s.replace('"', '').replace('%', '').strip()
            if cleaned == '' or cleaned == '-':
                return None
            # +/- 부호 처리
            return float(cleaned)
        except (ValueError, AttributeError):
            return None

    def _parse_int(self, s: str):
        if s is None:
            return None
        try:
            return int(s.replace('"', '').replace(',', '').strip())
        except (ValueError, AttributeError):
            return None
