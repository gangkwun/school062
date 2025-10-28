import requests
from bs4 import BeautifulSoup
import re
import io # 파일을 메모리에서 다루기 위해 필요
from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS # CORS 라이브러리 임포트

# ------------------------------------------------------------------
# [설정]
# ------------------------------------------------------------------
# (기존 price_list_crawler.py와 동일한 설정)
BASE_URL = "https://school062.com"
SEARCH_URL = f"{BASE_URL}/bbs/board.php"
LOGIN_URL = f"{BASE_URL}/bbs/login_check.php"
LOGIN_PAGE_URL = f"{BASE_URL}/bbs/login.php"

LOGIN_INFO = {
    'mb_id': 'kangkwun',
    'mb_password': 'kang1531',
    'url': f'{BASE_URL}/'
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36',
    'Referer': LOGIN_PAGE_URL
}

# ------------------------------------------------------------------
# [크롤링 함수]
# (파일 저장이 아닌, '파일 데이터'와 '이름'을 반환하도록 수정)
# ------------------------------------------------------------------
def perform_crawl(session, search_term):
    """
    로그인 된 세션과 검색어로 크롤링을 수행하고,
    (파일 데이터, 파일 이름) 튜플을 반환합니다.
    실패 시 (None, 에러 메시지)를 반환합니다.
    """
    params = {
        'bo_table': 'product_01',
        'sop': 'and',
        'sfl': 'wr_subject',
        'stx': search_term
    }
    
    print(f"'{search_term}' 검색 중...")
    headers_with_referer = HEADERS.copy()
    headers_with_referer['Referer'] = SEARCH_URL
    
    try:
        search_response = session.get(SEARCH_URL, params=params, headers=headers_with_referer)
        search_response.raise_for_status()

        soup = BeautifulSoup(search_response.text, 'html.parser')
        first_post_subject = soup.find('td', class_='td_subject')
        
        if not first_post_subject:
            return (None, "검색 결과가 없습니다.")

        post_link_tag = first_post_subject.find('a')
        if not post_link_tag or not post_link_tag.get('href'):
            return (None, "게시물 링크를 찾을 수 없습니다.")
            
        post_url = post_link_tag['href']
        print(f"게시물 찾음: {post_url}")

        post_response = session.get(post_url, headers=headers_with_referer)
        post_response.raise_for_status()
        
        post_soup = BeautifulSoup(post_response.text, 'html.parser')
        excel_link_tag = post_soup.find('a', href=re.compile(r'download\.php'))
        
        if not excel_link_tag:
            return (None, "엑셀 다운로드 링크를 찾지 못했습니다.")

        download_url = excel_link_tag['href']
        if not download_url.startswith('http'):
            download_url = f"{BASE_URL}{download_url}"
            
        print(f"다운로드 링크 찾음: {download_url}")

        # 5. 파일 다운로드 (데이터 반환)
        file_response = session.get(download_url, headers=headers_with_referer, stream=True)
        file_response.raise_for_status()
        
        # 파일 이름 찾기
        content_disposition = file_response.headers.get('Content-Disposition')
        filename = f"{search_term.replace(' ', '_')}.xls" # 기본값
        
        if content_disposition:
            fn = re.findall(r'filename\*?="?([^"]+)"?', content_disposition)
            if fn:
                try:
                    filename = re.sub(r'UTF-8\'\'', '', fn[0])
                    filename = requests.utils.unquote(filename, encoding='euc-kr') # 웹사이트 인코딩에 맞춰 디코딩
                except Exception as e:
                    print(f"파일명 디코딩 오류: {e}, 원본 사용: {fn[0]}")
                    filename = fn[0]

        print(f"파일 '{filename}' 데이터 전송 준비 완료")
        
        # 파일 데이터를 (데이터, 이름) 튜플로 반환
        return (file_response.content, filename)

    except requests.exceptions.RequestException as e:
        print(f"크롤링 오류 발생: {e}")
        return (None, f"크롤링 오류: {e}")
    except Exception as e:
        print(f"알 수 없는 오류: {e}")
        return (None, f"알 수 없는 오류: {e}")

# ------------------------------------------------------------------
# [Flask 웹 서버]
# ------------------------------------------------------------------
app = Flask(__name__)
CORS(app) # 모든 경로에서 CORS 허용

@app.route('/download', methods=['POST'])
def handle_download():
    """
    프론트엔드에서 '/download'로 POST 요청을 받으면 실행됩니다.
    """
    
    # 1. 프론트엔드에서 보낸 JSON 데이터 받기
    data = request.json
    search_term = data.get('search_term')
    
    if not search_term:
        return jsonify({"error": "검색어가 없습니다."}), 400

    # 2. 로그인 세션 생성 및 로그인 시도
    with requests.Session() as s:
        try:
            print(f"'{LOGIN_INFO['mb_id']}' 계정으로 로그인 시도...")
            s.headers.update(HEADERS)
            
            login_res = s.post(LOGIN_URL, data=LOGIN_INFO)
            login_res.raise_for_status()

            if "아이디 또는 패스워드가 틀립니다" in login_res.text or "회원아이디" in login_res.text:
                print("로그인 실패.")
                return jsonify({"error": "로그인 실패: 아이디 또는 패스워드를 확인하세요."}), 401
            
            print("로그인 성공!")

            # 3. 크롤링 함수 호출
            (file_content, filename) = perform_crawl(s, search_term)
            
            if file_content:
                # 4. 성공: 파일 데이터를 프론트엔드로 전송
                print("파일을 클라이언트로 전송합니다.")
                
                # 파일 데이터를 메모리(BytesIO)에 담기
                file_io = io.BytesIO(file_content)
                
                # send_file을 사용해 파일 응답 생성
                return send_file(
                    file_io,
                    mimetype='application/vnd.ms-excel', # 엑셀 파일 MimeType
                    as_attachment=True,
                    download_name=filename # 한글 파일명 지원
                )
            else:
                # 5. 실패: 에러 메시지 전송
                error_message = filename # 실패 시 filename 변수에는 에러 메시지가 담김
                print(f"오류: {error_message}")
                return jsonify({"error": error_message}), 404

        except requests.exceptions.RequestException as e:
            print(f"서버 오류: {e}")
            return jsonify({"error": f"로그인 요청 오류: {e}"}), 500
        except Exception as e:
            print(f"서버 내부 오류: {e}")
            return jsonify({"error": f"서버 내부 오류: {e}"}), 500

# ------------------------------------------------------------------
# [서버 실행]
# ------------------------------------------------------------------
if __name__ == "__main__":
    print("--- 단가표 다운로더 웹 서버 ---")
    print("HTML 파일(index.html)을 브라우저에서 열어주세요.")
    print("서버가 http://127.0.0.1:5000 에서 실행 중입니다...")
    app.run(debug=False, port=5000) # 디버그 모드 False로 변경, 포트 5000번
