import os, sys, tempfile
from flask import Flask, request, jsonify

# Add directory to sys.path so parser can be imported cleanly
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    import parser
except ImportError:
    from . import parser

app = Flask(__name__)

@app.after_request
def add_cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return resp

def do_preview():
    if request.method == 'OPTIONS':
        return ('', 204)
        
    if 'files' not in request.files and 'file' not in request.files:
        return jsonify({"error": "No file uploaded", "keys": list(request.files.keys())}), 400
        
    uploaded_files = request.files.getlist('files')
    if not uploaded_files:
        uploaded_files = [request.files['file']]
        
    previews = []
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        for f in uploaded_files:
            if not f.filename or not f.filename.lower().endswith('.pdf'):
                continue
            
            safe_filename = os.path.basename(f.filename)
            temp_path = os.path.join(tmp_dir, safe_filename)
            f.save(temp_path)
            
            try:
                res = parser.parse_uploaded_pdf(temp_path)
                txs = res.get('transactions', [])
                
                # Determine period and month
                from_d = res.get('statement_info', {}).get('from_date', '')
                to_d = res.get('statement_info', {}).get('to_date', '')
                
                det_month = "2026-10"
                det_year = 2026
                if to_d and '/' in to_d:
                    pts = to_d.split('/')
                    if len(pts) == 3:
                        det_month = f"{pts[2]}-{pts[1]}"
                        det_year = int(pts[2])
                elif txs and 'date' in txs[-1] and '/' in txs[-1]['date']:
                    pts = txs[-1]['date'].split('/')
                    det_month = f"{pts[2]}-{pts[1]}"
                    det_year = int(pts[2])

                tot_in = sum(t.get('credit', 0) for t in txs)
                tot_out = sum(t.get('debit', 0) for t in txs)
                start_b = txs[0].get('balance', 0) - txs[0].get('credit', 0) + txs[0].get('debit', 0) if txs else 0
                end_b = txs[-1].get('balance', 0) if txs else 0

                acc_id = 'snb_main'
                acc_name = 'البنك الأهلي السعودي - الحساب الرئيسي'
                # Check for sub account by IBAN / account number in first 16KB of file
                with open(temp_path, 'rb') as pdf_file:
                    header_bytes = pdf_file.read(16384)
                    if b'02400000714802' in header_bytes:
                        acc_id = 'snb_sub'
                        acc_name = 'البنك الأهلي السعودي - الحساب الفرعي (المصروفات)'

                previews.append({
                    "filename": safe_filename,
                    "account_id": acc_id,
                    "account_name": acc_name,
                    "month": det_month,
                    "year": det_year,
                    "period_from": from_d,
                    "period_to": to_d,
                    "total_inflows": round(tot_in, 2),
                    "total_outflows": round(tot_out, 2),
                    "net_flow": round(tot_in - tot_out, 2),
                    "start_balance": round(start_b, 2),
                    "end_balance": round(end_b, 2),
                    "tx_count": len(txs),
                    "new_count": len(txs),
                    "dup_count": 0,
                    "transactions": txs
                })
            except Exception as e:
                print(f"Error parsing {safe_filename}: {e}")
                
    return jsonify({"previews": previews, "count": len(previews)})

@app.route('/', methods=['GET', 'POST', 'OPTIONS'])
def root():
    if request.method == 'POST':
        return do_preview()
    return jsonify({
        "status": "online",
        "service": "SNB Statement AI Cloud Parser",
        "version": "2.0.0",
        "path": request.path
    })

@app.route('/api/preview-pdf', methods=['POST', 'OPTIONS'])
@app.route('/preview-pdf', methods=['POST', 'OPTIONS'])
def preview_endpoint():
    return do_preview()

@app.route('/api/health', methods=['GET'])
@app.route('/health', methods=['GET'])
def health_endpoint():
    return jsonify({
        "status": "online",
        "service": "SNB Statement AI Cloud Parser",
        "version": "2.0.0"
    })

# Universal catch-all so Vercel can never 404 regardless of rewrites
@app.route('/<path:subpath>', methods=['GET', 'POST', 'OPTIONS'])
def catch_all(subpath):
    if request.method == 'POST' or 'preview' in subpath:
        return do_preview()
    return jsonify({
        "status": "online",
        "service": "SNB Statement AI Cloud Parser",
        "version": "2.0.0",
        "subpath": subpath
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
