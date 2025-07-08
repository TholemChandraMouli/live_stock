from flask import Flask, render_template, jsonify, request
import requests
from datetime import datetime, timedelta
import time
import json

app = Flask(__name__)

# --- Configuration ---
# PASTE YOUR FINNHUB API KEY HERE:
FINNHUB_API_KEY = "d1m8k2pr01qvvurkq1e0d1m8k2pr01qvvurkq1eg"
BASE_URL = "https://finnhub.io/api/v1"

SYMBOLS = [
    "GOOGL", "IBM", "MSFT", "AAPL", "AMZN", "TSLA", "NVDA", "META", "NFLX", "INTC",
    "SBUX", "KO", "PEP", "NKE", "DIS", "V", "JPM", "GS"
]

# --- Helper to get Finnhub stock data ---
# This function will now accept a 'timestamp_override'
def get_stock_data(symbol, timestamp_override=None):
    quote_url = f"{BASE_URL}/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
    
    print(f"\n--- Fetching raw data for {symbol} from Finnhub ---")
    print(f"Request URL: {quote_url}")

    try:
        res = requests.get(quote_url)
        res.raise_for_status()
        data = res.json()
        print(f"Raw Finnhub Response for {symbol}: {json.dumps(data, indent=2)}")
    except (requests.exceptions.RequestException, ValueError) as e:
        print(f"Error fetching data for {symbol} from Finnhub: {e}")
        return None

    def safe_get_number(key):
        val = data.get(key)
        if isinstance(val, (int, float)):
            return val
        return None

    current_price = safe_get_number("c")
    prev_close = safe_get_number("pc")
    open_price = safe_get_number("o")
    high_price = safe_get_number("h")
    low_price = safe_get_number("l")
    #volume = safe_get_number("v")
    
    # Use the provided timestamp_override, or fallback to current time if not provided
    formatted_timestamp = timestamp_override if timestamp_override else datetime.now().strftime('%I:%M:%S %p')
    
    change = None
    percent_change = None

    if current_price is not None and prev_close is not None:
        change = round(current_price - prev_close, 2)
        if prev_close != 0:
            percent_change = round((change / prev_close) * 100, 2)
        else:
            percent_change = 0.0

    processed_quote = {
        "symbol": symbol,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": current_price,
        "prev_close": prev_close,
        "change": change,
        "percent_change": percent_change,
        "timestamp": formatted_timestamp, # Use the consistent timestamp here
        #"volume": volume
    }
    print(f"Processed Quote for {symbol}: {processed_quote}")
    return processed_quote

# --- API Endpoints ---

@app.route("/")
def home():
    stocks = []
    # Capture the time BEFORE fetching any stock data for consistency
    batch_fetch_time = datetime.now().strftime("%I:%M:%S %p")

    for symbol in SYMBOLS:
        # Pass the same batch_fetch_time to each get_stock_data call
        stocks.append(get_stock_data(symbol, timestamp_override=batch_fetch_time))
        time.sleep(0.5)
    
    # The dashboard's "Last Updated" time will also be this consistent time
    updated_time = batch_fetch_time
    return render_template("index.html", stocks=stocks, updated_time=updated_time)

@app.route('/chart-data')
def chart_data():
    symbol = request.args.get('symbol', 'AAPL')
    data_range = request.args.get('range', '1y')
    interval = request.args.get('interval', '1d')

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={data_range}&interval={interval}"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        result = data.get('chart', {}).get('result', [])
        if not result:
            return jsonify({'error': 'No chart data found for the given symbol and range.'}), 404
        
        result = result[0]
        timestamps = result.get('timestamp', [])
        closes = result.get('indicators', {}).get('quote', [{}])[0].get('close', [])

        labels = []
        prices = []

        for ts, close in zip(timestamps, closes):
            if isinstance(close, (int, float)) and close is not None:
                labels.append(datetime.fromtimestamp(ts).strftime('%Y-%m-%d'))
                prices.append(round(close, 2))

        return jsonify({
            'symbol': symbol,
            'labels': labels,
            'prices': prices
        })

    except Exception as e:
        print(f"Error fetching chart data for {symbol}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/calculate_comparison')
def calculate_comparison():
    symbols_str = request.args.get('symbols', '')
    start_investment_str = request.args.get('investment', '10000')
    years_str = request.args.get('years', '10')

    if not symbols_str:
        return jsonify({"error": "Please provide stock symbols."}), 400

    symbols = [s.strip().upper() for s in symbols_str.split(',') if s.strip()]
    
    try:
        start_investment = float(start_investment_str)
        investment_years = int(years_str)
        if investment_years <= 0:
            raise ValueError("Investment years must be positive.")
    except ValueError as e:
        return jsonify({"error": f"Invalid investment or years: {e}"}), 400

    comparison_results = []
    chart_data_points = []

    PLACEHOLDER_ANNUAL_YIELD = 0.02 # 2% annual yield for DRIP calculation

    for symbol in symbols:
        historical_data = requests.get(
            f"{request.url_root}chart-data?symbol={symbol}&range={investment_years}y&interval=1d"
        ).json()
        
        if historical_data.get('error'):
            print(f"Error fetching historical data for {symbol}: {historical_data['error']}")
            comparison_results.append({
                "symbol": symbol,
                "start_investment": start_investment,
                "annual_yield": "N/A",
                "end_value_no_drip": "N/A",
                "end_value_with_drip": "N/A",
                "chart_labels": [],
                "chart_prices": []
            })
            continue

        labels = historical_data.get('labels', [])
        prices = historical_data.get('prices', [])

        if not labels or len(prices) < 2:
            print(f"Not enough historical data for {symbol} for {investment_years} years.")
            comparison_results.append({
                "symbol": symbol,
                "start_investment": start_investment,
                "annual_yield": "N/A",
                "end_value_no_drip": "N/A",
                "end_value_with_drip": "N/A",
                "chart_labels": [],
                "chart_prices": []
            })
            continue

        start_price = prices[0]
        end_price = prices[-1]

        if start_price == 0:
            annual_growth_rate = 0
        else:
            annual_growth_rate = ((end_price / start_price)**(1 / investment_years)) - 1
        
        end_value_no_drip = start_investment * ((1 + annual_growth_rate)**investment_years)

        end_value_with_drip = start_investment * ((1 + annual_growth_rate + PLACEHOLDER_ANNUAL_YIELD)**investment_years)

        comparison_results.append({
            "symbol": symbol,
            "start_investment": start_investment,
            "annual_yield": f"{PLACEHOLDER_ANNUAL_YIELD * 100:.1f}%",
            "end_value_no_drip": round(end_value_no_drip, 2),
            "end_value_with_drip": round(end_value_with_drip, 2),
            "chart_labels": labels,
            "chart_prices": prices
        })

        normalized_prices = [(price / start_price) * start_investment for price in prices]
        chart_data_points.append({
            "symbol": symbol,
            "labels": labels,
            "prices": normalized_prices
        })
        time.sleep(0.5)

    return jsonify({
        "comparison_table": comparison_results,
        "comparison_chart_data": chart_data_points
    })

@app.route('/stock_data')
def stock_data():
    stock_list = []
    batch_fetch_time = datetime.now().strftime("%I:%M:%S %p") # Consistent time for dynamic updates too
    for symbol in SYMBOLS:
        quote = get_stock_data(symbol, timestamp_override=batch_fetch_time) # Pass consistent time
        if quote:
            data = {
                'symbol': symbol,
                'open': quote['open'],
                'close': quote['close'],
                'high': quote['high'],
                'low': quote['low'],
                'volume': quote['volume'],
                'change': quote['change'],
                'percent_change': quote['percent_change'],
                'timestamp': quote['timestamp'] # This will now be the formatted string
            }
        else:
            data = {
                'symbol': symbol,
                'open': 'N/A',
                'close': 'N/A',
                'high': 'N/A',
                'low': 'N/A',
                'volume': 'N/A',
                'change': 'N/A',
                'percent_change': 'N/A',
                'timestamp': 'N/A'
            }
        stock_list.append(data)
    return jsonify(stock_list)

if __name__ == "__main__":
    app.run(host="0.0.0.0"debug=True)
