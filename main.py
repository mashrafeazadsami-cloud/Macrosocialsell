import telebot
from telebot.types import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3, io, re, time
from datetime import datetime, timedelta, timezone

# ═════════════ CONFIG ═════════════
BOT_TOKEN = "8752771089:AAGSi7hA5BMVXp174voI0V8uWugGPTo8Sr0"
MAIN_ADMIN = 6058876211

bot = telebot.TeleBot(BOT_TOKEN)
bot.remove_webhook()

DB_PATH = "bot.db"
BDT = timedelta(hours=6)

def bd_time():
    return (datetime.now(timezone.utc) + BDT).strftime("%Y-%m-%d %H:%M:%S")

# ═════════════ DATABASE ═════════════
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.cursor()
    cur.executescript('''
        CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0, expected_balance REAL DEFAULT 0, joined TEXT, language TEXT DEFAULT 'bangla');
        CREATE TABLE IF NOT EXISTS id_types (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, price REAL, status TEXT DEFAULT 'active');
        CREATE TABLE IF NOT EXISTS submissions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, file_id TEXT, file_name TEXT, id_type TEXT, id_count INTEGER DEFAULT 1, price_per_id REAL, total_amount REAL, status TEXT DEFAULT 'pending', submit_date TEXT, approve_date TEXT, approved_amount REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS withdrawals (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, method TEXT, account TEXT, amount_tk REAL, amount_usd REAL, status TEXT DEFAULT 'pending', request_date TEXT, complete_date TEXT);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS used_uids (id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT UNIQUE, user_id INTEGER, submission_id INTEGER, added_date TEXT);
        CREATE TABLE IF NOT EXISTS banned (user_id INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS muted (user_id INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS monitor_groups (group_id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS data_groups (group_id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, username TEXT);
        CREATE TABLE IF NOT EXISTS balance_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, type TEXT, admin_id INTEGER, timestamp TEXT);
    ''')
    cur.execute("INSERT OR IGNORE INTO settings VALUES ('usd_rate','125')")
    cur.execute("INSERT OR IGNORE INTO settings VALUES ('min_withdraw','10')")
    cur.execute("INSERT OR IGNORE INTO settings VALUES ('submission_open','1')")
    cur.execute("INSERT OR IGNORE INTO admins VALUES (?,?)", (MAIN_ADMIN, "MainAdmin"))
    if cur.execute("SELECT COUNT(*) FROM id_types").fetchone()[0] == 0:
        for name, price in [("Cookies",4.0),("2FA",5.0),("Clone 13",13.0),("Number 00 Friend 2FA I'D",4.5),("Number 00 Cookies I'D",3.5)]:
            cur.execute("INSERT INTO id_types (name,price) VALUES (?,?)", (name, price))
    conn.commit()
    return conn, cur

conn, cursor = init_db()
user_state = {}
admin_state = {}

# ═════════════ HELPERS ═════════════
def setting(k, d="0"):
    r = cursor.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
    return r[0] if r else d

def usd_rate(): return float(setting('usd_rate','125'))
def min_wd(): return float(setting('min_withdraw','10'))

def is_admin(uid):
    return uid == MAIN_ADMIN or cursor.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,)).fetchone()

def is_banned(uid): return cursor.execute("SELECT 1 FROM banned WHERE user_id=?", (uid,)).fetchone()
def is_muted(uid): return cursor.execute("SELECT 1 FROM muted WHERE user_id=?", (uid,)).fetchone()

def monitor_log(*args):
    if len(args) == 1:
        txt = args[0]
        file_id = None
    elif len(args) == 2:
        txt = args[0]
        file_id = args[1]
    elif len(args) == 3:
        txt = f"🔍 Monitor Log\n\n👤 User: {args[0]}\n⚡ Action: {args[1]}\n📝 {args[2]}\n🕐 {bd_time()}"
        file_id = None
    elif len(args) == 4:
        txt = f"🔍 Monitor Log\n\n👤 User: {args[0]}\n📛 @{args[1]}\n⚡ Action: {args[2]}\n📝 {args[3]}\n🕐 {bd_time()}"
        file_id = None
    else:
        return
    for g in cursor.execute("SELECT group_id FROM monitor_groups").fetchall():
        try:
            bot.send_message(g[0], txt)
            if file_id:
                bot.send_document(g[0], file_id)
        except:
            pass

def data_log(txt, file_id=None):
    for g in cursor.execute("SELECT group_id FROM data_groups").fetchall():
        try:
            bot.send_message(g[0], txt, parse_mode="Markdown")
            if file_id:
                bot.send_document(g[0], file_id)
        except:
            pass

def notify_admins(txt, markup=None):
    ids = [MAIN_ADMIN] + [r[0] for r in cursor.execute("SELECT user_id FROM admins WHERE user_id!=?", (MAIN_ADMIN,)).fetchall()]
    for aid in ids:
        try:
            bot.send_message(aid, txt, parse_mode="Markdown", reply_markup=markup)
        except:
            pass

def main_menu(uid):
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.row("📤 Submit ID", "👤 My Profile")
    kb.row("💰 Balance", "💸 Withdraw")
    kb.row("💵 Price & Rules", "🌐 Language")
    if is_admin(uid):
        kb.row("👨‍💻 Admin Panel")
    return kb

def admin_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.row("📊 All Submissions", "📋 Withdrawals")
    kb.row("⏳ Pending Files", "📊 User Balance Info")
    kb.row("➕ Add ID Type", "❌ Remove ID Type")
    kb.row("🔄 Toggle Submission", "")
    kb.row("👥 User Management", "📡 Monitor Groups")
    kb.row("📤 Bot Data", "📅 Files by Date")
    kb.row("👑 Admin Management", "📢 Broadcast")
    kb.row("💱 USD Rate", "📊 Statistics")
    kb.row("🔙 Back")
    return kb

# ═════════════ START ═════════════
@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    un = msg.from_user.username or "Unknown"
    if not cursor.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone():
        cursor.execute("INSERT INTO users (user_id,username,joined) VALUES (?,?,?)", (uid, un, bd_time()))
        conn.commit()
    monitor_log(f"🚀 New User Started\n👤 User: {uid}\n📛 @{un}")
    data_log(f"🆕 New User\n👤 `{uid}` @{un}\n📅 {bd_time()}")
    bot.send_message(uid, f"✨ Welcome! 👋\n\n💎 Your earning journey begins!", reply_markup=main_menu(uid))

# ═════════════ LANGUAGE ═════════════
@bot.message_handler(func=lambda m: '🌐' in m.text)
def lang_menu(msg):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bangla"), InlineKeyboardButton("🇬🇧 English", callback_data="lang_english"))
    bot.send_message(msg.chat.id, "🌐 Select Language:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith('lang_'))
def lang_cb(c):
    lang = c.data[5:]
    cursor.execute("UPDATE users SET language=? WHERE user_id=?", (lang, c.from_user.id))
    conn.commit()
    monitor_log(f"🌐 Language Changed\n👤 User: {c.from_user.id}\n📝 Set to: {lang}")
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.send_message(c.message.chat.id, "✅ Language changed!", reply_markup=main_menu(c.from_user.id))

# ═════════════ PROFILE ═════════════
@bot.message_handler(func=lambda m: '👤' in m.text and 'Admin' not in m.text and 'Management' not in m.text)
def profile(msg):
    uid = msg.from_user.id
    u = cursor.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    if not u:
        return
    subs = cursor.execute("SELECT COUNT(*), SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END), SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END), SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) FROM submissions WHERE user_id=?", (uid,)).fetchone()
    wds = cursor.execute("SELECT COUNT(*), SUM(amount_tk) FROM withdrawals WHERE user_id=? AND status='completed'", (uid,)).fetchone()
    txt = f"""👤 *PROFILE*
🆔 `{u[0]}` | @{u[1]}
📅 Joined: {u[4]}

💰 Balance: *{u[2]:.2f}* Tk
⏳ Expected: *{u[3]:.2f}* Tk

📊 *Submissions*
📁 Total: {subs[0] or 0}
✅ Approved: {subs[1] or 0}
❌ Rejected: {subs[2] or 0}
⏳ Pending: {subs[3] or 0}

💸 *Withdrawals*
📤 Total: {wds[0] or 0}
💰 Total Amount: {wds[1] or 0:.2f} Tk"""
    monitor_log(f"👤 Profile Viewed\n👤 User: {uid}\n📛 @{u[1]}")
    bot.send_message(uid, txt, parse_mode="Markdown")

# ═════════════ BALANCE ═════════════
@bot.message_handler(func=lambda m: '💰' in m.text)
def balance(msg):
    uid = msg.from_user.id
    r = cursor.execute("SELECT balance, expected_balance FROM users WHERE user_id=?", (uid,)).fetchone()
    if r:
        monitor_log(f"💰 Balance Checked\n👤 User: {uid}")
        bot.send_message(uid, f"💰 *BALANCE*\n\n💎 Current: *{r[0]:.2f}* Tk\n⏳ Expected: *{r[1]:.2f}* Tk\n📌 Min Withdraw: *{min_wd()}* Tk", parse_mode="Markdown")

# ═════════════ PRICE ═════════════
@bot.message_handler(func=lambda m: '💵' in m.text)
def price(msg):
    uid = msg.from_user.id
    types = cursor.execute("SELECT name, price, status FROM id_types").fetchall()
    txt = "💵 *PRICE LIST*\n\n"
    for t in types:
        txt += f"📌 *{t[0]}*: {t[1]} Tk {'✅' if t[2]=='active' else '❌'}\n\n"
    txt += f"📌 Min Withdraw: *{min_wd()}* Tk\n💱 Exchange: *1$ = {usd_rate()}* Tk"
    monitor_log(f"💵 Price List Viewed\n👤 User: {uid}")
    bot.send_message(uid, txt, parse_mode="Markdown")

# ═════════════ SUBMISSION ═════════════
@bot.message_handler(func=lambda m: '📤' in m.text and 'Bot Data' not in m.text)
def submit_start(msg):
    uid = msg.from_user.id
    if is_banned(uid): return bot.send_message(uid, "🚫 Banned!")
    if is_muted(uid): return bot.send_message(uid, "🔇 Muted!")
    if setting('submission_open')!='1' and not is_admin(uid):
        return bot.send_message(uid, "⚠️ Submission closed!")
    types = cursor.execute("SELECT id, name, price FROM id_types WHERE status='active'").fetchall()
    if not types:
        return bot.send_message(uid, "No ID types!")
    kb = InlineKeyboardMarkup(row_width=1)
    for t in types:
        kb.add(InlineKeyboardButton(f"📦 {t[1]} - {t[2]} Tk", callback_data=f"sub_{t[0]}"))
    monitor_log(f"📤 Submission Menu Opened\n👤 User: {uid}")
    bot.send_message(uid, "📌 Select ID Type:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith('sub_'))
def sub_chosen(c):
    uid = c.from_user.id
    tid = int(c.data[4:])
    t = cursor.execute("SELECT name, price FROM id_types WHERE id=?", (tid,)).fetchone()
    if not t:
        return bot.answer_callback_query(c.id, "Invalid!")
    user_state[uid] = {'flow':'sub', 'tid':tid, 'price':t[1], 'name':t[0]}
    monitor_log(f"📦 ID Type Selected\n👤 User: {uid}\n📝 {t[0]} | {t[1]} Tk")
    bot.delete_message(c.message.chat.id, c.message.message_id)
    msg = bot.send_message(uid, f"📦 *{t[0]}*\n💰 {t[1]} Tk per ID\n\n📁 Send .xlsx file:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_file)

def process_file(msg):
    uid = msg.from_user.id
    if uid not in user_state:
        return
    if not msg.document or not msg.document.file_name.endswith('.xlsx'):
        return bot.send_message(uid, "❌ Only .xlsx files!")
    st = user_state[uid]
    uids = []
    dups = []
    try:
        import openpyxl
        file_info = bot.get_file(msg.document.file_id)
        wb = openpyxl.load_workbook(io.BytesIO(bot.download_file(file_info.file_path)))
        for row in wb.active.iter_rows(values_only=True):
            if row and row[0]:
                uid_str = re.sub(r'\D', '', str(row[0]))
                if uid_str.isdigit() and len(uid_str) >= 5:
                    if cursor.execute("SELECT 1 FROM used_uids WHERE uid=?", (uid_str,)).fetchone():
                        dups.append(uid_str)
                    else:
                        uids.append(uid_str)
    except:
        pass
    
    if not uids and not dups:
        monitor_log(f"⚠️ No Valid UIDs\n👤 User: {uid}")
        return bot.send_message(uid, "⚠️ No valid UIDs found!")
    
    if dups and not uids:
        monitor_log(f"⚠️ All Duplicate UIDs\n👤 User: {uid}\n📝 Total: {len(dups)}")
        return bot.send_message(uid, f"⚠️ *DUPLICATE DETECTED*\n📊 Total: {len(dups)} IDs\n🔄 All IDs already exist!\n❌ Submission rejected!", parse_mode="Markdown")
    
    if dups and uids:
        bot.send_message(uid, f"⚠️ *DUPLICATE DETECTED*\n📊 Total: {len(uids)+len(dups)} IDs\n🔄 Duplicate: {len(dups)} IDs\n✅ Valid: {len(uids)} IDs\n\nProcessing valid IDs...", parse_mode="Markdown")
    
    if uids:
        total = st['price'] * len(uids)
        cursor.execute("INSERT INTO submissions (user_id,file_id,file_name,id_type,id_count,price_per_id,total_amount,submit_date) VALUES (?,?,?,?,?,?,?,?)",
                       (uid, msg.document.file_id, msg.document.file_name, st['name'], len(uids), st['price'], total, bd_time()))
        sid = cursor.lastrowid
        for u in uids:
            cursor.execute("INSERT OR IGNORE INTO used_uids (uid,user_id,submission_id,added_date) VALUES (?,?,?,?)", (u, uid, sid, bd_time()))
        cursor.execute("UPDATE users SET expected_balance=expected_balance+? WHERE user_id=?", (total, uid))
        conn.commit()
        exp = cursor.execute("SELECT expected_balance FROM users WHERE user_id=?", (uid,)).fetchone()[0]
        
        bot.send_message(uid, f"✅ *SUBMISSION SUCCESSFUL*\n\n📦 {st['name']}\n📊 {len(uids)} IDs\n💰 {total} Tk\n⏳ Expected: {exp:.2f} Tk\n🆔 #{sid}", parse_mode="Markdown")
        
        admin_txt = f"📥 *NEW SUBMISSION #{sid}*\n\n👤 `{uid}` @{msg.from_user.username}\n📦 {st['name']}\n📊 {len(uids)} IDs\n💰 {total} Tk\n📅 {bd_time()}"
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("✅ Approve", callback_data=f"app_{sid}"), InlineKeyboardButton("❌ Reject", callback_data=f"rej_{sid}"))
        notify_admins(admin_txt, kb)
        
        monitor_log(uid, msg.from_user.username, f"📤 SUBMITTED", f"#{sid} - {st['name']} - {len(uids)} IDs")
        data_log(f"📥 *New Submission #{sid}*\n👤 {uid} @{msg.from_user.username}\n📦 {st['name']}\n📊 {len(uids)} IDs\n💰 {total} Tk\nStatus: ⏳ Pending\n📅 {bd_time()}", msg.document.file_id)
    
    del user_state[uid]

# ═════════════ APPROVE/REJECT ═════════════
@bot.callback_query_handler(func=lambda c: c.data.startswith('app_'))
def approve_cb(c):
    if not is_admin(c.from_user.id): return bot.answer_callback_query(c.id, "Denied")
    sid = int(c.data[4:])
    sub = cursor.execute("SELECT user_id, id_type, total_amount FROM submissions WHERE id=? AND status='pending'", (sid,)).fetchone()
    if not sub: return bot.answer_callback_query(c.id, "Already processed!")
    admin_state[c.from_user.id] = {'sid':sid, 'total':sub[2], 'uid':sub[0], 'type':sub[1]}
    bot.delete_message(c.message.chat.id, c.message.message_id)
    msg = bot.send_message(c.message.chat.id, f"✅ *Approve #{sid}*\nTotal: {sub[2]} Tk\n\nSend amount to add (0 to cancel):", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_approve_amount)

def process_approve_amount(msg):
    aid = msg.from_user.id
    if aid not in admin_state: return
    try: amt = float(msg.text)
    except: return bot.send_message(aid, "❌ Invalid!")
    st = admin_state[aid]
    if amt <= 0: del admin_state[aid]; return bot.send_message(aid, "Cancelled")
    if amt > st['total']: amt = st['total']
    cursor.execute("UPDATE submissions SET status='approved', approve_date=?, approved_amount=? WHERE id=?", (bd_time(), amt, st['sid']))
    cursor.execute("UPDATE users SET balance=balance+?, expected_balance=expected_balance-? WHERE user_id=?", (amt, st['total'], st['uid']))
    conn.commit()
    try: bot.send_message(st['uid'], f"✅ *Submission #{st['sid']} Approved!*\n💰 +{amt:.2f} Tk")
    except: pass
    bot.send_message(aid, f"✅ Approved #{st['sid']} +{amt} Tk")
    monitor_log(st['uid'], "user", f"✅ APPROVED #{st['sid']}", f"+{amt} Tk | Admin: {aid}")
    data_log(f"✅ *Submission Approved #{st['sid']}*\n👤 {st['uid']}\n📦 {st['type']}\n💰 +{amt:.2f} Tk\nAdmin: {aid}\n📅 {bd_time()}")
    del admin_state[aid]

@bot.callback_query_handler(func=lambda c: c.data.startswith('rej_'))
def reject_cb(c):
    if not is_admin(c.from_user.id): return bot.answer_callback_query(c.id, "Denied")
    sid = int(c.data[4:])
    sub = cursor.execute("SELECT user_id, id_type, total_amount FROM submissions WHERE id=? AND status='pending'", (sid,)).fetchone()
    if not sub: return bot.answer_callback_query(c.id, "Already processed!")
    cursor.execute("UPDATE submissions SET status='rejected' WHERE id=?", (sid,))
    cursor.execute("UPDATE users SET expected_balance=expected_balance-? WHERE user_id=?", (sub[2], sub[0]))
    conn.commit()
    try: bot.send_message(sub[0], f"❌ *Submission #{sid} Rejected*\n📦 {sub[1]}")
    except: pass
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.answer_callback_query(c.id, f"Rejected #{sid}")
    monitor_log(sub[0], "user", f"❌ REJECTED #{sid}", f"Admin: {c.from_user.id}")
    data_log(f"❌ *Submission Rejected #{sid}*\n👤 {sub[0]}\n📦 {sub[1]}\nAdmin: {c.from_user.id}\n📅 {bd_time()}")

# ═════════════ WITHDRAW ═════════════
@bot.message_handler(func=lambda m: '💸' in m.text)
def withdraw_start(msg):
    uid = msg.from_user.id
    if is_banned(uid): return bot.send_message(uid, "🚫 Banned!")
    if cursor.execute("SELECT 1 FROM withdrawals WHERE user_id=? AND status='pending'", (uid,)).fetchone():
        return bot.send_message(uid, "⏳ Already pending!")
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("💳 Bkash", callback_data="wd_bkash"),
           InlineKeyboardButton("💳 Nagad", callback_data="wd_nagad"),
           InlineKeyboardButton("₿ Binance", callback_data="wd_binance"))
    kb.add(InlineKeyboardButton("🔙 Back", callback_data="wd_back"))
    monitor_log(f"💸 Withdraw Menu Opened\n👤 User: {uid}")
    bot.send_message(uid, "💸 *Select Withdrawal Method:*", parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == 'wd_back')
def wd_back(c):
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.send_message(c.message.chat.id, "✅ Main Menu", reply_markup=main_menu(c.from_user.id))

@bot.callback_query_handler(func=lambda c: c.data == 'wd_confirm')
def wd_confirm_cb(c):
    uid = c.from_user.id
    if uid not in user_state: return bot.answer_callback_query(c.id, "Expired!")
    st = user_state[uid]
    usdt_amt = st['amount'] / usd_rate() if st['method'] == 'binance' else 0
    cursor.execute("INSERT INTO withdrawals (user_id,method,account,amount_tk,amount_usd,status,request_date) VALUES (?,?,?,?,?,?,?)",
                   (uid, st['method'], st['account'], st['amount'], round(usdt_amt, 2), 'pending', bd_time()))
    wid = cursor.lastrowid
    conn.commit()
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.send_message(uid, f"✅ *Withdraw Request #{wid} Sent!*\n⏳ Pending admin approval\n💎 Balance unchanged", reply_markup=main_menu(uid))
    
    admin_txt = f"💸 *New Withdrawal #{wid}*\n\n👤 `{uid}` @{c.from_user.username}\n💳 {st['method'].upper()}\n📱 {st['account']}\n💰 {st['amount']} Tk"
    if st['method'] == 'binance': admin_txt += f"\n💱 ${usdt_amt:.2f} USDT"
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Approve", callback_data=f"wd_app_{wid}"), InlineKeyboardButton("❌ Reject", callback_data=f"wd_rej_{wid}"))
    notify_admins(admin_txt, kb)
    
    monitor_log(uid, c.from_user.username, f"💸 WITHDRAW REQUEST #{wid}", f"{st['amount']} Tk via {st['method']}")
    data_log(f"💸 *New Withdrawal #{wid}*\n👤 {uid} @{c.from_user.username}\n💳 {st['method'].upper()}\n📱 {st['account']}\n💰 {st['amount']} Tk" + (f"\n💱 ${usdt_amt:.2f} USDT" if st['method']=='binance' else "") + f"\nStatus: ⏳ Pending\n📅 {bd_time()}")
    del user_state[uid]

@bot.callback_query_handler(func=lambda c: c.data == 'wd_cancel')
def wd_cancel_cb(c):
    if c.from_user.id in user_state: del user_state[c.from_user.id]
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.send_message(c.message.chat.id, "❌ Cancelled", reply_markup=main_menu(c.from_user.id))

@bot.callback_query_handler(func=lambda c: c.data.startswith('wd_app_'))
def wd_app(c):
    if not is_admin(c.from_user.id): return bot.answer_callback_query(c.id, "Denied")
    wid = int(c.data[7:])
    row = cursor.execute("SELECT user_id, amount_tk, amount_usd, method FROM withdrawals WHERE id=? AND status='pending'", (wid,)).fetchone()
    if not row: return bot.answer_callback_query(c.id, "Already processed!")
    cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (row[1], row[0]))
    cursor.execute("UPDATE withdrawals SET status='completed', complete_date=? WHERE id=?", (bd_time(), wid))
    conn.commit()
    try: bot.send_message(row[0], f"✅ *Withdrawal #{wid} Approved!*\n💰 {row[1]:.2f} Tk sent" + (f"\n💱 ${row[2]:.2f} USDT" if row[3]=='binance' else ""))
    except: pass
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.answer_callback_query(c.id, "Approved")
    monitor_log(f"✅ Withdrawal #{wid} Approved\n👤 User: {row[0]}\n📝 {row[1]} Tk | Admin: {c.from_user.id}")
    data_log(f"✅ *Withdrawal Approved #{wid}*\n👤 {row[0]}\n💰 {row[1]} Tk\nAdmin: {c.from_user.id}\n📅 {bd_time()}")

@bot.callback_query_handler(func=lambda c: c.data.startswith('wd_rej_'))
def wd_rej(c):
    if not is_admin(c.from_user.id): return bot.answer_callback_query(c.id, "Denied")
    wid = int(c.data[7:])
    row = cursor.execute("SELECT user_id FROM withdrawals WHERE id=? AND status='pending'", (wid,)).fetchone()
    if not row: return bot.answer_callback_query(c.id, "Already processed!")
    cursor.execute("UPDATE withdrawals SET status='rejected' WHERE id=?", (wid,))
    conn.commit()
    try: bot.send_message(row[0], f"❌ *Withdrawal #{wid} Rejected*")
    except: pass
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.answer_callback_query(c.id, "Rejected")
    monitor_log(f"❌ Withdrawal #{wid} Rejected\n👤 User: {row[0]}\n📝 Admin: {c.from_user.id}")
    data_log(f"❌ *Withdrawal Rejected #{wid}*\n👤 {row[0]}\nAdmin: {c.from_user.id}\n📅 {bd_time()}")

@bot.callback_query_handler(func=lambda c: c.data.startswith('wd_') and c.data not in ['wd_back','wd_confirm','wd_cancel'])
def wd_method(c):
    method = c.data[3:]
    uid = c.from_user.id
    bal = cursor.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
    if not bal or bal[0] < min_wd(): return bot.answer_callback_query(c.id, f"Min {min_wd()} Tk")
    user_state[uid] = {'flow':'wd', 'method':method}
    monitor_log(f"💳 Withdraw Method Selected\n👤 User: {uid}\n📝 {method.upper()}")
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.send_message(uid, f"💳 *{method.upper()}*\n\nSend your {method.upper()} account number:", parse_mode="Markdown")
    bot.register_next_step_handler(c.message, wd_account)

def wd_account(msg):
    uid = msg.from_user.id
    if uid not in user_state: return
    user_state[uid]['account'] = msg.text.strip()
    user_state[uid]['flow'] = 'wd_amt'
    bal = cursor.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()[0]
    monitor_log(f"📱 Withdraw Account Entered\n👤 User: {uid}")
    bot.send_message(uid, f"💰 *Enter Amount*\n\nBalance: `{bal:.2f} Tk`\nMin: `{min_wd()} Tk`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, wd_amount)

def wd_amount(msg):
    uid = msg.from_user.id
    if uid not in user_state: return
    try: amount = float(msg.text)
    except: return bot.send_message(uid, "❌ Invalid!")
    bal = cursor.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()[0]
    if amount < min_wd() or amount > bal: return bot.send_message(uid, f"❌ Min {min_wd()} Tk / Insufficient")
    st = user_state[uid]; st['amount'] = amount
    monitor_log(f"💰 Withdraw Amount Entered\n👤 User: {uid}\n📝 {amount} Tk")
    confirm_txt = f"📋 *Confirm Withdrawal*\n\n💳 {st['method'].upper()}\n📱 {st['account']}\n💰 {amount:.2f} Tk"
    if st['method'] == 'binance':
        usdt = amount / usd_rate()
        confirm_txt += f"\n💱 ${usdt:.2f} USDT"
    confirm_txt += "\n\n⚠️ Balance deducted after admin approval."
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Confirm", callback_data="wd_confirm"), InlineKeyboardButton("❌ Cancel", callback_data="wd_cancel"))
    bot.send_message(uid, confirm_txt, parse_mode="Markdown", reply_markup=kb)

# ═════════════ ADMIN PANEL ═════════════
@bot.message_handler(func=lambda m: '👨‍💻' in m.text)
def admin_panel(msg):
    if not is_admin(msg.from_user.id): return bot.send_message(msg.chat.id, "🚫 Access Denied!")
    monitor_log(f"🔰 Admin Panel Opened\n👤 Admin: {msg.from_user.id}")
    bot.send_message(msg.chat.id, "🔰 *Admin Panel*", parse_mode="Markdown", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: '🔙' in m.text)
def back(msg):
    bot.send_message(msg.chat.id, "✅ Main Menu", reply_markup=main_menu(msg.from_user.id))

def abtn(text):
    return lambda m: is_admin(m.from_user.id) and m.text == text

@bot.message_handler(func=abtn("📊 All Submissions"))
def all_subs(msg):
    data = cursor.execute("SELECT id, user_id, id_type, id_count, total_amount, status, submit_date FROM submissions ORDER BY id DESC LIMIT 30").fetchall()
    txt = "📊 *ALL SUBMISSIONS*\n\n"
    for s in data:
        emoji = "✅" if s[5]=='approved' else "❌" if s[5]=='rejected' else "⏳"
        txt += f"#{s[0]} | {s[6][:10]} | 👤 {s[1]}\n└ {s[2]} | {s[3]}x | {s[4]} Tk | {emoji}\n\n"
    bot.send_message(msg.chat.id, txt or "None", parse_mode="Markdown")

@bot.message_handler(func=abtn("📋 Withdrawals"))
def all_wds(msg):
    data = cursor.execute("SELECT w.id, w.user_id, u.username, w.method, w.amount_tk, w.amount_usd, w.status, w.request_date FROM withdrawals w LEFT JOIN users u ON w.user_id=u.user_id ORDER BY w.id DESC LIMIT 30").fetchall()
    txt = "📋 *WITHDRAWALS*\n\n"
    for w in data:
        emoji = "✅" if w[6]=='completed' else "❌" if w[6]=='rejected' else "⏳"
        txt += f"#{w[0]} | @{w[2] or w[1]} | {w[3]} | {w[4]} Tk"
        if w[3] == 'binance': txt += f" | ${w[5]:.2f}"
        txt += f" | {emoji} | {w[7][:16]}\n"
    kb = InlineKeyboardMarkup(row_width=2)
    for w in data:
        if w[6] == 'pending':
            kb.add(InlineKeyboardButton(f"✅ #{w[0]} Approve", callback_data=f"wd_app_{w[0]}"), InlineKeyboardButton(f"❌ #{w[0]} Reject", callback_data=f"wd_rej_{w[0]}"))
    bot.send_message(msg.chat.id, txt or "None", parse_mode="Markdown", reply_markup=kb)

@bot.message_handler(func=abtn("⏳ Pending Files"))
def pending_files(msg):
    subs = cursor.execute("SELECT id, user_id, id_type, id_count, total_amount, submit_date FROM submissions WHERE status='pending' ORDER BY id DESC LIMIT 30").fetchall()
    if not subs: return bot.send_message(msg.chat.id, "✅ No pending files!")
    txt = "⏳ *PENDING FILES*\n\n"
    for s in subs:
        txt += f"#{s[0]} | 👤 {s[1]} | 📦 {s[2]} | 📊 {s[3]}x | 💰 {s[4]} Tk | 📅 {s[5][:10]}\n"
    kb = InlineKeyboardMarkup(row_width=2)
    for s in subs[:12]:
        kb.add(InlineKeyboardButton(f"✅ #{s[0]}", callback_data=f"app_{s[0]}"), InlineKeyboardButton(f"❌ #{s[0]}", callback_data=f"rej_{s[0]}"))
    bot.send_message(msg.chat.id, txt, parse_mode="Markdown", reply_markup=kb)

@bot.message_handler(func=abtn("📊 User Balance Info"))
def bal_info(msg):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("➕ Add Balance", callback_data="ub_add"), InlineKeyboardButton("➖ Remove Balance", callback_data="ub_remove"))
    kb.add(InlineKeyboardButton("👥 All Users", callback_data="ub_all"), InlineKeyboardButton("📋 Full History", callback_data="ub_history"))
    bot.send_message(msg.chat.id, "📊 *User Balance Info*", parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == 'ub_add')
def ub_add(c): 
    admin_state[c.from_user.id] = {'action':'add'}
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.send_message(c.message.chat.id, "Send username or ID:")
    bot.register_next_step_handler(c.message, bal_user)

@bot.callback_query_handler(func=lambda c: c.data == 'ub_remove')
def ub_rem(c):
    admin_state[c.from_user.id] = {'action':'remove'}
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.send_message(c.message.chat.id, "Send username or ID:")
    bot.register_next_step_handler(c.message, bal_user)

def bal_user(msg):
    aid = msg.from_user.id
    if aid not in admin_state: return
    q = msg.text.strip().replace('@','')
    u = cursor.execute("SELECT user_id, username, balance FROM users WHERE user_id=? OR username=?", (q if q.isdigit() else 0, q)).fetchone()
    if not u: return bot.send_message(aid, "❌ Not found!")
    admin_state[aid].update({'uid':u[0],'uname':u[1],'bal':u[2]})
    act = "add" if admin_state[aid]['action']=='add' else "remove"
    bot.send_message(aid, f"👤 @{u[1]} | 💰 {u[2]:.2f} Tk\n\nEnter amount to {act}:")
    bot.register_next_step_handler(msg, bal_amt)

def bal_amt(msg):
    aid = msg.from_user.id
    if aid not in admin_state: return
    try: amt = float(msg.text)
    except: return bot.send_message(aid, "❌ Invalid!")
    if amt <= 0: return bot.send_message(aid, "Positive only")
    st = admin_state[aid]
    if st['action']=='remove' and amt > st['bal']: return bot.send_message(aid, "Insufficient")
    st['amt'] = amt
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Confirm", callback_data="bal_ok"), InlineKeyboardButton("❌ Cancel", callback_data="bal_no"))
    bot.send_message(aid, f"🤔 {'Add' if st['action']=='add' else 'Remove'} {amt:.2f} Tk?", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == 'bal_ok')
def bal_ok(c):
    aid = c.from_user.id
    if aid not in admin_state: return bot.answer_callback_query(c.id, "Invalid")
    st = admin_state[aid]
    if st['action']=='add':
        new_bal = st['bal'] + st['amt']
        cursor.execute("UPDATE users SET balance=? WHERE user_id=?", (new_bal, st['uid']))
        cursor.execute("INSERT INTO balance_log (user_id,amount,type,admin_id,timestamp) VALUES (?,?,?,?,?)", (st['uid'], st['amt'], 'add', aid, bd_time()))
    else:
        new_bal = st['bal'] - st['amt']
        cursor.execute("UPDATE users SET balance=? WHERE user_id=?", (new_bal, st['uid']))
        cursor.execute("INSERT INTO balance_log (user_id,amount,type,admin_id,timestamp) VALUES (?,?,?,?,?)", (st['uid'], st['amt'], 'remove', aid, bd_time()))
    conn.commit()
    try: bot.send_message(st['uid'], f"💰 {st['action']}ed {st['amt']:.2f} Tk | Balance: {new_bal:.2f} Tk")
    except: pass
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.send_message(aid, f"✅ Updated: {new_bal:.2f} Tk")
    monitor_log(f"💰 Balance {st['action']}ed by Admin {aid}\n👤 User: {st['uid']}\n📝 {st['amt']} Tk")
    data_log(f"💰 *Balance {st['action']}ed*\n👤 {st['uid']}\nAmount: {st['amt']} Tk\nAdmin: {aid}\n📅 {bd_time()}")
    del admin_state[aid]

@bot.callback_query_handler(func=lambda c: c.data == 'bal_no')
def bal_no(c):
    if c.from_user.id in admin_state: del admin_state[c.from_user.id]
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.send_message(c.message.chat.id, "Cancelled")

@bot.callback_query_handler(func=lambda c: c.data == 'ub_all')
def ub_all(c):
    bot.delete_message(c.message.chat.id, c.message.message_id)
    users = cursor.execute("SELECT user_id, username, balance FROM users ORDER BY balance DESC").fetchall()
    txt = "👥 *All Users*\n\n" + "\n".join([f"{i}. @{u[1]} ({u[0]}) - {u[2]:.2f} Tk" for i,u in enumerate(users,1)])
    txt += f"\n📊 Total: {len(users)}"
    bot.send_message(c.message.chat.id, txt, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == 'ub_history')
def ub_hist(c):
    bot.delete_message(c.message.chat.id, c.message.message_id)
    logs = cursor.execute("SELECT timestamp, (SELECT username FROM users WHERE user_id=bl.user_id), amount, type FROM balance_log bl ORDER BY id DESC LIMIT 60").fetchall()
    wds = cursor.execute("SELECT request_date, (SELECT username FROM users WHERE user_id=w.user_id), amount_tk, status, id FROM withdrawals w ORDER BY id DESC LIMIT 60").fetchall()
    events = [(l[0], f"💰 {'+' if l[3]=='add' else '-'}{l[2]:.2f} Tk by @{l[1]}") for l in logs]
    events += [(w[0], f"💸 #{w[4]}: {w[2]:.2f} Tk {'✅' if w[3]=='completed' else '❌' if w[3]=='rejected' else '⏳'} by @{w[1]}") for w in wds]
    events.sort(key=lambda x: x[0], reverse=True)
    txt = "📋 *Full History*\n\n" + "\n".join([f"`{ts[:16]}` {d}" for ts,d in events[:60]]) if events else "No history"
    bot.send_message(c.message.chat.id, txt, parse_mode="Markdown")

# ═════════════ ADD/REMOVE ID ═════════════
@bot.message_handler(func=abtn("➕ Add ID Type"))
def add_id(msg): 
    bot.send_message(msg.chat.id, "Format: Name | Price\nExample: Test | 10")
    bot.register_next_step_handler(msg, lambda m: (cursor.execute("INSERT INTO id_types (name,price) VALUES (?,?)", [x.strip() for x in m.text.split('|',1)]), conn.commit(), bot.send_message(m.chat.id, "✅ Added")))

@bot.message_handler(func=abtn("❌ Remove ID Type"))
def rem_id(msg):
    kb = InlineKeyboardMarkup(row_width=1)
    for t in cursor.execute("SELECT id, name FROM id_types").fetchall(): kb.add(InlineKeyboardButton(f"❌ {t[1]}", callback_data=f"del_id_{t[0]}"))
    bot.send_message(msg.chat.id, "Select:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith('del_id_'))
def del_id(c):
    cursor.execute("DELETE FROM id_types WHERE id=?", (c.data[7:],))
    conn.commit()
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.answer_callback_query(c.id, "Removed")

# ═════════════ TOGGLE/USD/STATS ═════════════
@bot.message_handler(func=abtn("🔄 Toggle Submission"))
def toggle_sub(msg):
    cur = setting('submission_open','1')
    new = '0' if cur=='1' else '1'
    cursor.execute("UPDATE settings SET value=? WHERE key='submission_open'", (new,))
    conn.commit()
    bot.send_message(msg.chat.id, f"🔄 Submission: {'✅ OPEN' if new=='1' else '❌ CLOSED'}")

@bot.message_handler(func=abtn("💱 USD Rate"))
def usd_cmd(msg):
    bot.send_message(msg.chat.id, f"Current: 1$ = {usd_rate()} Tk\nSend new rate:")
    bot.register_next_step_handler(msg, lambda m: (cursor.execute("UPDATE settings SET value=? WHERE key='usd_rate'", (str(float(m.text)),)), conn.commit(), bot.send_message(m.chat.id, f"✅ Updated to {float(m.text)}")))

@bot.message_handler(func=abtn("📊 Statistics"))
def stats(msg):
    users = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    sub = cursor.execute("SELECT COUNT(*), SUM(total_amount) FROM submissions WHERE status='approved'").fetchone()
    wd = cursor.execute("SELECT COUNT(*), SUM(amount_tk) FROM withdrawals WHERE status='completed'").fetchone()
    bot.send_message(msg.chat.id, f"📊 *Statistics*\n👥 Users: {users}\n✅ Approved Subs: {sub[0]} ({sub[1] or 0:.2f} Tk)\n✅ Completed WDs: {wd[0]} ({wd[1] or 0:.2f} Tk)\n💱 Rate: 1$ = {usd_rate()} Tk", parse_mode="Markdown")

# ═════════════ MONITOR GROUPS ═════════════
@bot.message_handler(func=abtn("📡 Monitor Groups"))
def mon_grp(msg):
    groups = cursor.execute("SELECT group_id FROM monitor_groups").fetchall()
    txt = "📡 *Monitor Groups*\n" + "\n".join([f"`{g[0]}`" for g in groups]) if groups else "None"
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("➕ Add", callback_data="mg_add"), InlineKeyboardButton("❌ Remove", callback_data="mg_rem"))
    bot.send_message(msg.chat.id, txt, parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == 'mg_add')
def mg_add(c):
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.send_message(c.message.chat.id, "Send group ID (-100xxx):")
    bot.register_next_step_handler(c.message, lambda m: mg_add_exec(m))

def mg_add_exec(msg):
    try:
        bot.send_message(msg.text, "✅ Monitor bot connected!")
        cursor.execute("INSERT OR IGNORE INTO monitor_groups VALUES (?)", (msg.text,))
        conn.commit()
        bot.send_message(msg.chat.id, f"✅ Added: `{msg.text}`", parse_mode="Markdown")
    except:
        bot.send_message(msg.chat.id, "❌ Failed! Check ID and bot admin status.")

@bot.callback_query_handler(func=lambda c: c.data == 'mg_rem')
def mg_rem(c):
    kb = InlineKeyboardMarkup(row_width=1)
    for g in cursor.execute("SELECT group_id FROM monitor_groups").fetchall(): kb.add(InlineKeyboardButton(f"❌ {g[0]}", callback_data=f"mg_del_{g[0]}"))
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.send_message(c.message.chat.id, "Select:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith('mg_del_'))
def mg_del(c):
    cursor.execute("DELETE FROM monitor_groups WHERE group_id=?", (c.data[7:],))
    conn.commit()
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.answer_callback_query(c.id, "Removed")

# ═════════════ BROADCAST ═════════════
@bot.message_handler(func=abtn("📢 Broadcast"))
def broadcast(msg):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📝 Text", callback_data="bc_text"), InlineKeyboardButton("📎 Media", callback_data="bc_media"))
    bot.send_message(msg.chat.id, "📢 *Broadcast*", parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == 'bc_text')
def bc_text(c):
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.send_message(c.message.chat.id, "Send message:")
    bot.register_next_step_handler(c.message, lambda m: exec_broadcast(m, 'text'))

@bot.callback_query_handler(func=lambda c: c.data == 'bc_media')
def bc_media(c):
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.send_message(c.message.chat.id, "Send file:")
    bot.register_next_step_handler(c.message, lambda m: exec_broadcast(m, 'media'))

def exec_broadcast(msg, typ):
    users = [u[0] for u in cursor.execute("SELECT user_id FROM users").fetchall()]
    s = f = 0
    for u in users:
        try:
            if typ == 'text': bot.send_message(u, msg.text)
            elif msg.document: bot.send_document(u, msg.document.file_id)
            elif msg.photo: bot.send_photo(u, msg.photo[-1].file_id)
            elif msg.video: bot.send_video(u, msg.video.file_id)
            s += 1
        except: f += 1
    bot.send_message(msg.chat.id, f"✅ Sent: {s} | ❌ Failed: {f}")

# ═════════════ USER MANAGEMENT ═════════════
@bot.message_handler(func=abtn("👥 User Management"))
def user_mgmt(msg):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("🚫 Ban", callback_data="um_ban"), InlineKeyboardButton("🔇 Mute", callback_data="um_mute"),
           InlineKeyboardButton("✅ Unban", callback_data="um_unban"), InlineKeyboardButton("🔊 Unmute", callback_data="um_unmute"))
    bot.send_message(msg.chat.id, "👥 *User Management*", parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == 'um_ban')
def um_ban(c): bot.delete_message(c.message.chat.id,c.message.message_id); bot.send_message(c.message.chat.id,"Send user ID:"); bot.register_next_step_handler(c.message, lambda m: (cursor.execute("INSERT OR IGNORE INTO banned VALUES (?)",(int(m.text),)), conn.commit(), bot.send_message(m.chat.id,"✅ Banned")))
@bot.callback_query_handler(func=lambda c: c.data == 'um_mute')
def um_mute(c): bot.delete_message(c.message.chat.id,c.message.message_id); bot.send_message(c.message.chat.id,"Send user ID:"); bot.register_next_step_handler(c.message, lambda m: (cursor.execute("INSERT OR IGNORE INTO muted VALUES (?)",(int(m.text),)), conn.commit(), bot.send_message(m.chat.id,"✅ Muted")))
@bot.callback_query_handler(func=lambda c: c.data == 'um_unban')
def um_unban(c):
    bans = cursor.execute("SELECT user_id FROM banned").fetchall()
    if not bans: return bot.answer_callback_query(c.id,"No banned")
    kb = InlineKeyboardMarkup(row_width=1)
    for b in bans: kb.add(InlineKeyboardButton(f"Unban {b[0]}", callback_data=f"unban_{b[0]}"))
    bot.delete_message(c.message.chat.id,c.message.message_id)
    bot.send_message(c.message.chat.id,"Select:",reply_markup=kb)
@bot.callback_query_handler(func=lambda c: c.data.startswith('unban_'))
def unban(c): cursor.execute("DELETE FROM banned WHERE user_id=?",(c.data[6:],)); conn.commit(); bot.delete_message(c.message.chat.id,c.message.message_id); bot.answer_callback_query(c.id,"Unbanned")
@bot.callback_query_handler(func=lambda c: c.data == 'um_unmute')
def um_unmute(c):
    mutes = cursor.execute("SELECT user_id FROM muted").fetchall()
    kb = InlineKeyboardMarkup(row_width=1)
    for m in mutes: kb.add(InlineKeyboardButton(f"Unmute {m[0]}", callback_data=f"unmute_{m[0]}"))
    bot.delete_message(c.message.chat.id,c.message.message_id)
    bot.send_message(c.message.chat.id,"Select:",reply_markup=kb)
@bot.callback_query_handler(func=lambda c: c.data.startswith('unmute_'))
def unmute(c): cursor.execute("DELETE FROM muted WHERE user_id=?",(c.data[7:],)); conn.commit(); bot.delete_message(c.message.chat.id,c.message.message_id); bot.answer_callback_query(c.id,"Unmuted")

# ═════════════ ADMIN MANAGEMENT ═════════════
@bot.message_handler(func=abtn("👑 Admin Management"))
def adm_mgmt(msg):
    if msg.from_user.id != MAIN_ADMIN: return bot.send_message(msg.chat.id,"Only main admin")
    admins = cursor.execute("SELECT user_id, username FROM admins").fetchall()
    txt = "👑 *Admins*\n" + "\n".join([f"⭐ @{a[1]} ({a[0]})" for a in admins])
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("➕ Add", callback_data="adm_add"), InlineKeyboardButton("❌ Remove", callback_data="adm_rem"))
    bot.send_message(msg.chat.id, txt, parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == 'adm_add')
def adm_add(c):
    if c.from_user.id != MAIN_ADMIN: return bot.answer_callback_query(c.id,"Only main")
    bot.delete_message(c.message.chat.id,c.message.message_id)
    bot.send_message(c.message.chat.id,"Send username:")
    bot.register_next_step_handler(c.message, lambda m: (cursor.execute("INSERT INTO admins (user_id,username) SELECT user_id,? FROM users WHERE username=?",(m.text.strip().replace('@',''), m.text.strip().replace('@',''))), conn.commit(), bot.send_message(m.chat.id,"✅ Added")))

@bot.callback_query_handler(func=lambda c: c.data == 'adm_rem')
def adm_rem(c):
    adms = cursor.execute("SELECT user_id, username FROM admins WHERE user_id!=?", (MAIN_ADMIN,)).fetchall()
    if not adms: return bot.answer_callback_query(c.id,"No other admins")
    kb = InlineKeyboardMarkup(row_width=1)
    for a in adms: kb.add(InlineKeyboardButton(f"❌ @{a[1]}", callback_data=f"adm_del_{a[0]}"))
    bot.delete_message(c.message.chat.id,c.message.message_id)
    bot.send_message(c.message.chat.id,"Select:",reply_markup=kb)
@bot.callback_query_handler(func=lambda c: c.data.startswith('adm_del_'))
def adm_del_cb(c): cursor.execute("DELETE FROM admins WHERE user_id=?",(c.data[8:],)); conn.commit(); bot.delete_message(c.message.chat.id,c.message.message_id); bot.answer_callback_query(c.id,"Removed")

# ═════════════ BOT DATA ═════════════
@bot.message_handler(func=abtn("📤 Bot Data"))
def bot_data_cmd(msg):
    groups = cursor.execute("SELECT group_id FROM data_groups").fetchall()
    txt = f"📤 *Bot Data Groups*\nConnected: {len(groups)}"
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("➕ Add", callback_data="dg_add"), InlineKeyboardButton("❌ Remove", callback_data="dg_rem"),
           InlineKeyboardButton("📋 List", callback_data="dg_list"), InlineKeyboardButton("📤 Export", callback_data="dg_export"))
    bot.send_message(msg.chat.id, txt, parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == 'dg_add')
def dg_add(c):
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.send_message(c.message.chat.id, "Send group ID (-100xxx):")
    bot.register_next_step_handler(c.message, lambda m: dg_add_exec(m))

def dg_add_exec(msg):
    try:
        bot.send_message(msg.text, "✅ Bot data group connected! All data will be auto-sent here including files & withdrawals with status.")
        cursor.execute("INSERT OR IGNORE INTO data_groups VALUES (?)", (msg.text,))
        conn.commit()
        bot.send_message(msg.chat.id, f"✅ Added: `{msg.text}`", parse_mode="Markdown")
    except:
        bot.send_message(msg.chat.id, "❌ Failed! Check ID and bot admin status.")

@bot.callback_query_handler(func=lambda c: c.data == 'dg_rem')
def dg_rem(c):
    kb = InlineKeyboardMarkup(row_width=1)
    for g in cursor.execute("SELECT group_id FROM data_groups").fetchall(): kb.add(InlineKeyboardButton(f"❌ {g[0]}", callback_data=f"dg_del_{g[0]}"))
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.send_message(c.message.chat.id, "Select:", reply_markup=kb)
@bot.callback_query_handler(func=lambda c: c.data.startswith('dg_del_'))
def dg_del(c):
    cursor.execute("DELETE FROM data_groups WHERE group_id=?", (c.data[7:],))
    conn.commit()
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.answer_callback_query(c.id, "Removed")

@bot.callback_query_handler(func=lambda c: c.data == 'dg_list')
def dg_list(c):
    groups = cursor.execute("SELECT group_id FROM data_groups").fetchall()
    txt = "📋 *Data Groups*\n" + "\n".join([f"`{g[0]}`" for g in groups]) if groups else "None"
    bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.send_message(c.message.chat.id, txt, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == 'dg_export')
def dg_export_cb(c):
    bot.delete_message(c.message.chat.id, c.message.message_id)
    for g in cursor.execute("SELECT group_id FROM data_groups").fetchall():
        try:
            users = cursor.execute("SELECT user_id, username, balance, expected_balance FROM users").fetchall()
            txt = "📊 *All Users*\n" + "\n".join([f"👤 {u[0]} @{u[1]} | 💰 {u[2]:.2f} | ⏳ {u[3]:.2f}" for u in users])
            bot.send_message(g[0], txt[:4000], parse_mode="Markdown")
        except: pass
    bot.send_message(c.message.chat.id, "✅ Data exported!")

# ═════════════ FILES BY DATE ═════════════
@bot.message_handler(func=abtn("📅 Files by Date"))
def files_date(msg):
    bot.send_message(msg.chat.id, "📅 Enter date (DD-MM-YYYY or DD):")
    bot.register_next_step_handler(msg, lambda m: date_files(m))

def date_files(msg):
    d = msg.text.strip()
    try:
        if '-' in d: target = datetime.strptime(d, "%d-%m-%Y").strftime("%Y-%m-%d")
        else: target = datetime(datetime.now().year, datetime.now().month, int(d)).strftime("%Y-%m-%d")
    except: return bot.send_message(msg.chat.id, "❌ Invalid date!")
    subs = cursor.execute("SELECT id, user_id, id_type, id_count, total_amount, status FROM submissions WHERE date(submit_date)=?", (target,)).fetchall()
    if not subs: return bot.send_message(msg.chat.id, "📅 No files found")
    txt = f"📅 *Files for {target}*\n\n" + "\n".join([f"#{s[0]} 👤{s[1]} {s[2]} x{s[3]} {s[4]}Tk {'✅' if s[5]=='approved' else '❌' if s[5]=='rejected' else '⏳'}" for s in subs])
    bot.send_message(msg.chat.id, txt, parse_mode="Markdown")

print("✅ Bot running with FULL Monitor Log + Data Log + All Features")
bot.infinity_polling(timeout=60, interval=0)