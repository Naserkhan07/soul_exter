//+------------------------------------------------------------------+
//| JarvisBridge.mq5 - executes Jarvis Trader signals inside MT5     |
//|                                                                  |
//| SETUP (on your Windows machine running MetaTrader 5):            |
//| 1. Run the Jarvis Trader bot (python run.py) on the same machine |
//|    or a machine MT5 can reach, note the URL (e.g. 127.0.0.1:8000)|
//| 2. In MT5: Tools > Options > Expert Advisors >                   |
//|    check "Allow WebRequest for listed URL" and add:              |
//|    http://127.0.0.1:8000                                         |
//| 3. Compile this EA in MetaEditor, attach it to ANY chart.        |
//| 4. It polls /mt5/commands every few seconds and places the       |
//|    orders (with TP/SL) on your MT5 account using your login      |
//|    - you never share your MT5 password with the bot.             |
//+------------------------------------------------------------------+
#property strict

input string JarvisURL   = "http://127.0.0.1:8000";
input int    PollSeconds = 5;
input double LotCap      = 0.50;   // max lot size safety cap
input bool   EnableLive  = false;  // MUST be set true to actually trade

datetime lastPoll = 0;

// Map Jarvis symbols to your broker's MT5 symbol names here:
string MapSymbol(string s)
  {
   if(s=="XAUUSD") return "XAUUSD";
   if(s=="EURUSD") return "EURUSD";
   if(s=="GBPUSD") return "GBPUSD";
   if(s=="USDJPY") return "USDJPY";
   if(s=="BTCUSDT") return "BTCUSD";
   if(s=="ETHUSDT") return "ETHUSD";
   return s;
  }

int OnInit(){ EventSetTimer(PollSeconds); return(INIT_SUCCEEDED); }
void OnDeinit(const int reason){ EventKillTimer(); }

string GetJson(string url)
  {
   char data[]; char result[]; string headers;
   int res = WebRequest("GET", url, "", 5000, data, result, headers);
   if(res==-1){ Print("WebRequest failed - add URL in Options>Expert Advisors"); return ""; }
   return CharArrayToString(result);
  }

// very small JSON field extractor
string JField(string json, string key)
  {
   int p = StringFind(json, "\""+key+"\"");
   if(p<0) return "";
   p = StringFind(json, ":", p) + 1;
   while(StringGetCharacter(json,p)==' ') p++;
   bool q = (StringGetCharacter(json,p)=='"');
   if(q) p++;
   int e = p;
   while(e<StringLen(json))
     {
      ushort c = StringGetCharacter(json,e);
      if(q && c=='"') break;
      if(!q && (c==',' || c=='}')) break;
      e++;
     }
   return StringSubstr(json, p, e-p);
  }

void OnTimer()
  {
   string body = GetJson(JarvisURL + "/mt5/commands");
   if(body=="" || StringFind(body,"\"commands\": []")>=0 || StringFind(body,"\"commands\":[]")>=0)
      return;

   // naive split on "{"id" occurrences inside commands array
   int pos = 0;
   while(true)
     {
      pos = StringFind(body, "\"action\"", pos);
      if(pos<0) break;
      string chunk = StringSubstr(body, pos-200>0?pos-200:0, 700);
      string side   = JField(chunk, "side");
      string symbol = MapSymbol(JField(chunk, "symbol"));
      double tp     = StringToDouble(JField(chunk, "tp"));
      double sl     = StringToDouble(JField(chunk, "sl"));
      double conf   = StringToDouble(JField(chunk, "confidence"));
      pos += 8;

      if(!EnableLive){ Print("Jarvis signal (dry-run): ",side," ",symbol," TP=",tp," SL=",sl," conf=",conf); continue; }
      if(symbol=="" || (side!="BUY" && side!="SELL")) continue;

      double lot = MathMin(LotCap, 0.01 * MathMax(1.0, conf/20.0));
      MqlTradeRequest req; MqlTradeResult res;
      ZeroMemory(req); ZeroMemory(res);
      req.action   = TRADE_ACTION_DEAL;
      req.symbol   = symbol;
      req.volume   = NormalizeDouble(lot,2);
      req.type     = (side=="BUY") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      req.price    = (side=="BUY") ? SymbolInfoDouble(symbol,SYMBOL_ASK)
                                   : SymbolInfoDouble(symbol,SYMBOL_BID);
      req.sl       = NormalizeDouble(sl, (int)SymbolInfoInteger(symbol,SYMBOL_DIGITS));
      req.tp       = NormalizeDouble(tp, (int)SymbolInfoInteger(symbol,SYMBOL_DIGITS));
      req.deviation= 20;
      req.magic    = 20260815;
      req.comment  = "JarvisTrader";
      if(!OrderSend(req,res))
         Print("OrderSend failed: ", res.retcode);
      else
         Print("Jarvis LIVE order: ", side, " ", symbol, " lot=", lot);
     }
  }
