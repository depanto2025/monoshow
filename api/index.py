import io, re
from flask import Flask, request, jsonify
import pypdf

app = Flask(__name__)

@app.after_request
def add_cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return resp

def clean_arabic(text):
    if not text:
        return ''
    mapping = {
        'رداص يلخاد ليوحت': 'تحويل داخلي صادر',
        'دراو يلخاد ليوحت': 'تحويل داخلي وارد',
        'بتار عاديا': 'إيداع راتب',
        'بتار عاديٕا': 'إيداع راتب',
        'زفاوح عاديا': 'إيداع حوافز',
        'زفاوح عاديٕا': 'إيداع حوافز',
        'ياب كيوك ةرداص ةيلود ةلاوح': 'حوالة دولية صادرة كويك باي',
        'حواله دوليه صادره كويك باي': 'حوالة دولية صادرة كويك باي',
        'سداد تاعوفدم': 'مدفوعات سداد',
        'دادس تاعوفدم': 'مدفوعات سداد',
        'ةفاضملا ةميقلا ةبيرض': 'ضريبة القيمة المضافة',
        'ضريبه القيمه المضافه': 'ضريبة القيمة المضافة',
        'شراء نقاط بيع': 'شراء نقاط بيع',
        'GooglePay شراء نقاط بيع': 'GooglePay شراء نقاط بيع'
    }
    for k, v in mapping.items():
        text = text.replace(k, v)
    return text.strip()

def categorize_tx(tx_type, desc, credit, debit):
    s = (desc + ' ' + tx_type)
    if credit > 0:
        if '02400000714802' in s: return 'تحويل وارد من حسابه الفرعي بالأهلي'
        if 'حوافز' in s or 'زفاوح' in s: return 'حوافز شركة الدواء'
        if 'المواطن' in s: return 'إيداع دعم حساب المواطن'
        if 'راتب' in s or 'الدواء' in s or 'بتار' in s: return 'رواتب شركة الدواء'
        return 'إيداعات أخرى'
    else:
        if '02400000714802' in s or ('2477247726' in s and '024' in s): return 'تحويل لحساب الأهلي الفرعي'
        if 'raghi' in s.lower() or 'rajhi' in s.lower() or 'الراجحي' in s:
            if debit in [0.5, 0.08, 0.25, 0.04]: return 'رسوم بنكية وضريبة'
            return 'تحويل لحساب الراجحي'
        if 'حج' in s: return 'سداد وزارة الحج والعمرة'
        if 'ejar' in s.lower() or (debit == 6800.0 and 'سداد' in s): return 'سداد إيجار السكن (EJAR)'
        if 'كهرباء' in s or 'مقيم' in s: return 'سداد فواتير وخدمات حكومية'
        if 'qpay' in s.lower() or 'كويك باي' in s:
            if debit in [16.0, 2.4]: return 'رسوم بنكية وضريبة'
            return 'حوالات كويك باي للأهل (مصر)'
        if debit in [16.0, 2.4, 0.5, 0.08, 1.0, 0.15] or 'رسوم' in s or 'ضريبة' in s:
            return 'رسوم بنكية وضريبة'
        if 'GooglePay' in s or 'نقاط بيع' in s or 'شراء' in s:
            return 'سحوبات ومشتريات يومية'
        return 'مصاريف أخرى'

def parse_pdf_stream(pdf_bytes, filename=''):
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    fullText = '\n'.join([p.extract_text() or '' for p in reader.pages])

    first_page = reader.pages[0].extract_text() or ''
    acc_id = 'snb_main'
    acc_name = 'البنك الأهلي السعودي - الحساب الرئيسي'
    if '02400000714802' in first_page and '6900000268104' not in first_page:
        acc_id = 'snb_sub'
        acc_name = 'البنك الأهلي السعودي - الحساب الفرعي (المصروفات)'

    all_dates = re.findall(r'(\d{2}/\d{2}/20\d{2})', fullText)
    from_date = all_dates[0] if len(all_dates) >= 2 else (all_dates[0] if all_dates else '')
    to_date = all_dates[1] if len(all_dates) >= 2 else from_date

    det_month = '2026-10'
    det_year = 2026
    if to_date and '/' in to_date:
        pts = to_date.split('/')
        if len(pts) == 3:
            det_month = f'{pts[2]}-{pts[1]}'
            det_year = int(pts[2])

    rawLines = [l.strip() for l in fullText.split('\n') if l.strip()]
    txs = []

    is_format_a = 'STATEMENT MOVEMENTS' in fullText or 'Credit Debit Balance' in fullText or 'TOTAL CREDITS' in fullText or 'STARTING BALANCE' in fullText

    if is_format_a:
        i = 0
        while i < len(rawLines):
            line = rawLines[i]
            mDate = re.search(r'(\d{2}/\d{2}/20\d{2})', line)
            if mDate and not any(k in line for k in ['From:', 'To:', 'STATEMENT DATE']):
                dateVal = mDate.group(1)
                inlineType = line.replace(dateVal, '').strip()
                timeVal = ''
                typeVal = inlineType
                idx = i + 1
                if not typeVal:
                    if idx < len(rawLines) and re.match(r'^\d{2}:\d{2}$', rawLines[idx]):
                        timeVal = rawLines[idx]
                        idx += 1
                    if idx < len(rawLines) and not re.search(r'[\d,]+\.\d{2}', rawLines[idx]):
                        typeVal = rawLines[idx]
                        idx += 1
                else:
                    if idx < len(rawLines) and re.match(r'^\d{2}:\d{2}$', rawLines[idx]):
                        timeVal = rawLines[idx]
                        idx += 1

                descLines = []
                creditVal, debitVal, balVal = 0.0, 0.0, 0.0

                while idx < len(rawLines):
                    curr = rawLines[idx]
                    if re.search(r'\d{2}/\d{2}/20\d{2}', curr) or any(k in curr for k in ['STATEMENT MOVEMENTS', 'STARTING BALANCE', 'Dear Customer', 'Page']):
                        break
                    num_matches = re.findall(r'([\d,]+\.\d{2})', curr)
                    if num_matches:
                        nums = [float(n.replace(',', '')) for n in num_matches]
                        if len(nums) >= 2:
                            amt = nums[0]
                            balVal = nums[1]
                            is_cr = any(k in typeVal for k in ['ايداع', 'إيداع', 'حوافز', 'راتب', 'وارد'])
                            if is_cr: creditVal = amt
                            else: debitVal = amt
                        elif len(nums) == 1:
                            amt = nums[0]
                            if balVal == 0 and (debitVal > 0 or creditVal > 0):
                                balVal = amt
                            elif debitVal == 0 and creditVal == 0:
                                is_cr = any(k in typeVal for k in ['ايداع', 'إيداع', 'حوافز', 'راتب', 'وارد'])
                                if is_cr: creditVal = amt
                                else: debitVal = amt
                    else:
                        if not any(curr.startswith(p) for p in ['Page', 'Date', 'Transaction', 'Account', 'SA44', 'ES41']):
                            descLines.append(curr)
                    idx += 1

                if balVal > 0 or debitVal > 0 or creditVal > 0:
                    clean_type = clean_arabic(typeVal) or ('إيداع بنكي' if creditVal > 0 else 'عملية مصرفية')
                    clean_desc = clean_arabic(' | '.join(descLines)) or clean_type
                    cat = categorize_tx(clean_type, clean_desc, creditVal, debitVal)
                    txs.append({
                        'date': dateVal,
                        'time': timeVal,
                        'type': clean_type,
                        'description': clean_desc,
                        'credit': creditVal,
                        'debit': debitVal,
                        'balance': balVal,
                        'category': cat,
                        'account_id': acc_id
                    })
                i = idx
                continue
            i += 1
    else:
        # Format B (كشوفات الحساب الفرعي ومصروفات نقاط البيع)
        i = 0
        while i < len(rawLines):
            line = rawLines[i]
            mDate = re.search(r'(\d{2}/\d{2}/20\d{2})', line)
            if mDate:
                dateVal = mDate.group(1)
                typeVal = line.replace(dateVal, '').strip()
                timeVal = rawLines[i+1] if i+1 < len(rawLines) and re.match(r'^\d{2}:\d{2}$', rawLines[i+1]) else ''
                balVal, debitVal, creditVal = 0.0, 0.0, 0.0
                descLines = []
                j = i - 1
                while j >= 0 and j >= i - 15:
                    prev = rawLines[j]
                    if re.search(r'\d{2}/\d{2}/20\d{2}', prev): break
                    num_matches = re.findall(r'([\d,]+\.\d{2})', prev)
                    if num_matches:
                        nums = [float(n.replace(',', '')) for n in num_matches]
                        if len(nums) >= 2 and balVal == 0:
                            balVal = nums[0]
                            amt = nums[1]
                            if any(k in typeVal for k in ['ايداع', 'وارد', 'حوافز', 'راتب']): creditVal = amt
                            else: debitVal = amt
                        elif len(nums) == 1:
                            if balVal == 0: balVal = nums[0]
                            elif debitVal == 0 and creditVal == 0:
                                amt = nums[0]
                                if any(k in typeVal for k in ['ايداع', 'وارد', 'حوافز', 'راتب']): creditVal = amt
                                else: debitVal = amt
                    else:
                        if not any(prev.startswith(p) for p in ['Page', 'Balance', 'Debit', 'Credit']):
                            descLines.insert(0, prev)
                    j -= 1

                if balVal > 0 or debitVal > 0 or creditVal > 0:
                    clean_type = clean_arabic(typeVal) or ('إيداع بنكي' if creditVal > 0 else 'عملية شراء')
                    clean_desc = clean_arabic(' | '.join(descLines)) or clean_type
                    cat = categorize_tx(clean_type, clean_desc, creditVal, debitVal)
                    txs.append({
                        'date': dateVal,
                        'time': timeVal,
                        'type': clean_type,
                        'description': clean_desc,
                        'credit': creditVal,
                        'debit': debitVal,
                        'balance': balVal,
                        'category': cat,
                        'account_id': acc_id
                    })
            i += 1

    tot_in = sum(t['credit'] for t in txs)
    tot_out = sum(t['debit'] for t in txs)
    start_b = txs[0]['balance'] - txs[0]['credit'] + txs[0]['debit'] if txs else 0
    end_b = txs[-1]['balance'] if txs else 0

    return {
        'filename': filename,
        'account_id': acc_id,
        'account_name': acc_name,
        'month': det_month,
        'year': det_year,
        'period_from': from_date,
        'period_to': to_date,
        'total_inflows': round(tot_in, 2),
        'total_outflows': round(tot_out, 2),
        'net_flow': round(tot_in - tot_out, 2),
        'start_balance': round(start_b, 2),
        'end_balance': round(end_b, 2),
        'tx_count': len(txs),
        'transactions': txs
    }

def handle_upload():
    if 'files' not in request.files and 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    uploaded_files = request.files.getlist('files') or [request.files['file']]
    previews = []
    for f in uploaded_files:
        if not f.filename or not f.filename.lower().endswith('.pdf'): continue
        safe_name = f.filename
        content = f.read()
        try:
            preview = parse_pdf_stream(content, safe_name)
            previews.append(preview)
        except Exception as e:
            print("Parse error:", e)
    return jsonify({"previews": previews, "count": len(previews)})

@app.route('/', methods=['GET', 'POST', 'OPTIONS'])
def root():
    if request.method == 'POST': return handle_upload()
    return jsonify({"status": "online", "service": "SNB Statement AI Cloud Parser", "version": "3.0.0"})

@app.route('/api/preview-pdf', methods=['POST', 'OPTIONS'])
@app.route('/preview-pdf', methods=['POST', 'OPTIONS'])
def preview():
    return handle_upload()

@app.route('/api/health', methods=['GET'])
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "online", "service": "SNB Statement AI Cloud Parser", "version": "3.0.0"})

@app.route('/<path:subpath>', methods=['GET', 'POST', 'OPTIONS'])
def catch_all(subpath):
    if request.method == 'POST' or 'preview' in subpath: return handle_upload()
    return jsonify({"status": "online", "service": "SNB Statement AI Cloud Parser", "version": "3.0.0", "path": subpath})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
