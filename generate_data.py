import os
import random
import datetime
import pandas as pd
import numpy as np
from pathlib import Path

# Setup output dir
WORKSPACE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = WORKSPACE_DIR / "hackerrank-orchestrate-august26" / "dataset_large"
OUTPUT_DIR.mkdir(exist_ok=True)

print(f"Generating synthetic dataset in {OUTPUT_DIR}...")

# Set random seed for reproducibility
random.seed(42)
np.random.seed(42)

# Templates
SCAM_TEMPLATES = [
    "Urgent: Your bank account is blocked. Verify now: {link}",
    "Congratulations! You won a cash prize of {num}. Claim here: {link}",
    "Use login code: {num} to access your payout profile. Do not share this.",
    "Verify your mobile wallet immediately to avoid service disruption: {link}",
    "A clearance amount of {num} is pending. Pay the processing fee at {link}",
    "Your package is on hold. Pay tax fee of {num} to release it: {link}"
]

URGENT_TEMPLATES = [
    "Water valve leak in basement! Plumber is coming. Valve room is closed.",
    "Tower B elevator is stuck. Maintenance team is on the way ASAP.",
    "Important sync meeting started. Join immediately.",
    "Emergency circular: Fire alarm testing tomorrow at 10 AM.",
    "Security gate issue: Please keep main doors locked today.",
    "Can you call me immediately? It's an emergency."
]

EVENT_TEMPLATES = [
    "Circular: School field trip scheduled for next Friday. Please sign consent form.",
    "Monthly society meeting tomorrow at 7 PM in the club house. Agenda: maintenance.",
    "Project kickoff scheduled for Monday at 10 AM. Agenda attached.",
    "Final exam timetable released. Check student portal for details.",
    "Annual maintenance scheduled for the main water pump on Tuesday.",
    "Community clean-up drive this Saturday from 8 AM onwards."
]

PAYMENT_TEMPLATES = [
    "Maintenance bill of {num} is due by Friday. Pay to society account.",
    "Your monthly subscription renewal fee of {num} is pending.",
    "A refund of {num} has been processed for your order.",
    "Rent payment of {num} received for this month. Thank you.",
    "Invoice {num} generated for consulting services. Please pay today.",
    "Electricity bill of {num} is ready. Last date is next week."
]

PROMOTION_TEMPLATES = [
    "Big Sale! Get 50% off on all fashion items today only at {link}",
    "Weekend getaway discount code: FLY50. Book your trip now: {link}",
    "Stream the latest blockbusters for free this weekend at {link}",
    "Order food now and get 30% discount using code FOOD30 at {link}",
    "Upgrade your telecom plan today to get extra 10GB data: {link}",
    "Limited time offer: Get premium membership at just {num}/year: {link}"
]

GREETING_TEMPLATES = [
    "Good morning! Have a blessed and beautiful day ahead.",
    "Wishing you a very happy weekend filled with joy.",
    "Hello! Hope you are doing well today.",
    "Have a nice day ahead! Stay positive.",
    "Happy Monday! Let's make this week productive.",
    "Good night! Sweet dreams."
]

FORWARD_TEMPLATES = [
    "Fwd: Pass this message to 10 friends for good luck!",
    "Forwarded: A beautiful message about life and happiness...",
    "Watch this viral video: {link} - forwarded many times.",
    "Fwd: Important advice: drink water every morning.",
    "Forwarded: True story of inspiration...",
    "Fwd: Share this with your groups to spread awareness."
]

PERSONAL_TEMPLATES = [
    "Are we meeting today for lunch?",
    "Hey, did you finish the assignment?",
    "Can you call me when you are free?",
    "I'll be home by 7 PM. See you.",
    "What are you doing this weekend?",
    "Thanks for the help yesterday!"
]

def make_random_text(category):
    link = random.choice(["http://bit.ly/claim-win", "http://verify-bank.com", "http://login-verify.net", "http://sale.co"])
    num = f"${random.randint(10, 5000)}"
    if category == 'scam':
        return random.choice(SCAM_TEMPLATES).format(link=link, num=num)
    elif category == 'urgent':
        return random.choice(URGENT_TEMPLATES)
    elif category == 'event':
        return random.choice(EVENT_TEMPLATES)
    elif category == 'payment':
        return random.choice(PAYMENT_TEMPLATES).format(num=num)
    elif category == 'promotion':
        return random.choice(PROMOTION_TEMPLATES).format(link=link, num=num)
    elif category == 'greeting':
        return random.choice(GREETING_TEMPLATES)
    elif category == 'forward':
        return random.choice(FORWARD_TEMPLATES).format(link=link)
    else:
        return random.choice(PERSONAL_TEMPLATES)

# 1. Users
num_users = 100
user_ids = [f"u_{i:03d}" for i in range(1, num_users + 1)]
user_names = [f"User Name {i}" for i in range(1, num_users + 1)]
dnd_windows = ["22:00-07:00", "23:00-08:00", "00:00-06:00", "None"]
users_df = pd.DataFrame({
    'user_id': user_ids,
    'user_name': user_names,
    'do_not_disturb_window': [random.choice(dnd_windows) for _ in range(num_users)],
    'messages_opened_30d': np.random.randint(50, 500, size=num_users),
    'messages_replied_30d': np.random.randint(10, 200, size=num_users),
    'notifications_dismissed_30d': np.random.randint(5, 100, size=num_users),
    'messages_reported_30d': np.random.randint(0, 10, size=num_users)
})

# 2. Groups
num_groups = 30
group_ids = [f"group_{i:03d}" for i in range(1, num_groups + 1)]
group_names = [f"Group {i}" for i in range(1, num_groups + 1)]
group_types = ['family', 'friends', 'coworker', 'project', 'society', 'school_group']
groups_df = pd.DataFrame({
    'group_id': group_ids,
    'group_name': group_names,
    'group_type': [random.choice(group_types) for _ in range(num_groups)]
})

# 3. Group Members
gm_records = []
for g_id in group_ids:
    g_type = groups_df[groups_df['group_id'] == g_id]['group_type'].values[0]
    members = random.sample(user_ids, k=random.randint(5, 20))
    admins = random.sample(members, k=max(1, len(members) // 5))
    for m in members:
        role = 'admin' if m in admins else 'member'
        group_muted = 1 if (g_type in ['society', 'school_group'] and random.random() > 0.4) else 0
        gm_records.append({
            'group_id': g_id,
            'user_id': m,
            'role': role,
            'group_muted_by_user': group_muted
        })
group_members_df = pd.DataFrame(gm_records)

# 4. Business Accounts
num_businesses = 50
biz_ids = [f"biz_{i:03d}" for i in range(1, num_businesses + 1)]
biz_names = [f"Business {i}" for i in range(1, num_businesses + 1)]
biz_cats = ['ecommerce_delivery', 'ride_booking', 'telecom', 'logistics', 'payments', 'streaming', 'travel', 'fashion', 'other']
businesses_df = pd.DataFrame({
    'business_id': biz_ids,
    'business_name': biz_names,
    'category': [random.choice(biz_cats) for _ in range(num_businesses)],
    'verified': [1 if random.random() > 0.3 else 0 for _ in range(num_businesses)]
})

# 5. User Business History (Opt-ins)
ubh_records = []
for u_id in user_ids:
    selected_biz = random.sample(biz_ids, k=random.randint(5, 15))
    for b_id in selected_biz:
        ubh_records.append({
            'user_id': u_id,
            'business_id': b_id,
            'allows_promotions': 1 if random.random() > 0.3 else 0
        })
ubh_df = pd.DataFrame(ubh_records)

# 6. Message History (10,000 rows)
hist_rows = 10000
hist_ids = [f"message_{i:06d}" for i in range(1, hist_rows + 1)]
hist_users = [random.choice(user_ids) for _ in range(hist_rows)]
hist_convs = [random.choice(['personal', 'group', 'business']) for _ in range(hist_rows)]

hist_records = []
base_time = datetime.datetime(2026, 7, 1, 9, 0, 0)

for idx, m_id in enumerate(hist_ids):
    u_id = hist_users[idx]
    conv_type = hist_convs[idx]
    
    g_id = np.nan
    b_id = np.nan
    sender_id = np.nan
    
    if conv_type == 'group':
        user_groups = group_members_df[group_members_df['user_id'] == u_id]['group_id'].values
        if len(user_groups) > 0:
            g_id = random.choice(user_groups)
            group_m = group_members_df[group_members_df['group_id'] == g_id]['user_id'].values
            senders = [m for m in group_m if m != u_id]
            sender_id = random.choice(senders) if len(senders) > 0 else random.choice(user_ids)
        else:
            conv_type = 'personal'
            
    if conv_type == 'business':
        user_biz = ubh_df[ubh_df['user_id'] == u_id]['business_id'].values
        if len(user_biz) > 0:
            b_id = random.choice(user_biz)
        else:
            conv_type = 'personal'
            
    if conv_type == 'personal':
        sender_id = random.choice([x for x in user_ids if x != u_id])
        
    created_at = (base_time + datetime.timedelta(minutes=idx * 4)).strftime("%Y-%m-%d %H:%M")
    
    category = random.choice(['scam', 'urgent', 'event', 'payment', 'promotion', 'greeting', 'forward', 'personal'])
    text = make_random_text(category)
    
    media_type = np.nan
    media_id = np.nan
    if random.random() > 0.8:
        media_type = random.choice(['image', 'voice'])
        media_id = f"img_{random.randint(100, 999)}" if media_type == 'image' else f"vn_{random.randint(100, 999)}"
        
    forwarded = random.randint(0, 10) if category == 'forward' else 0
    
    hist_records.append({
        'message_id': m_id,
        'user_id': u_id,
        'conversation_type': conv_type,
        'group_id': g_id,
        'business_id': b_id,
        'sender_user_id': sender_id,
        'created_at': created_at,
        'message_text': text,
        'media_type': media_type,
        'media_id': media_id,
        'forwarded_count': forwarded
    })

history_df = pd.DataFrame(hist_records)

# 7. Message Events (Aligning with History)
events_records = []
for idx, row in history_df.iterrows():
    u_id = row['user_id']
    m_id = row['message_id']
    
    opened = 0
    replied = 0
    dismissed = 0
    muted = 0
    reported = 0
    
    text = row['message_text']
    text_lower = text.lower()
    
    if any(x in text_lower for x in ['verify', 'block', 'congratulations', 'won']):
        if random.random() > 0.7:
            reported = 1
            muted = 1
        else:
            dismissed = 1
    elif any(x in text_lower for x in ['fwd', 'forward']):
        if random.random() > 0.8:
            opened = 1
        else:
            dismissed = 1
    elif any(x in text_lower for x in ['good morning', 'wishing']):
        if random.random() > 0.5:
            opened = 1
            if random.random() > 0.5:
                replied = 1
        else:
            dismissed = 1
    elif any(x in text_lower for x in ['sale', 'discount', 'free']):
        if random.random() > 0.9:
            opened = 1
        else:
            dismissed = 1
    elif any(x in text_lower for x in ['leak', 'emergency', 'stuck']):
        opened = 1
        replied = 1
    else:
        opened = 1
        if random.random() > 0.4:
            replied = 1
            
    events_records.append({
        'user_id': u_id,
        'message_id': m_id,
        'message_opened': opened,
        'message_replied': replied,
        'notification_dismissed': dismissed,
        'muted_after_message': muted,
        'message_reported': reported
    })

events_df = pd.DataFrame(events_records)

# 8. Target Messages (1,000 messages) and ground truth
target_rows = 1000
target_ids = [f"msg_{i:04d}" for i in range(1, target_rows + 1)]
target_records = []
ground_truth_records = []
target_base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)

for idx, m_id in enumerate(target_ids):
    u_id = random.choice(user_ids)
    conv_type = random.choice(['personal', 'group', 'business'])
    
    g_id = np.nan
    b_id = np.nan
    sender_id = np.nan
    
    if conv_type == 'group':
        user_groups = group_members_df[group_members_df['user_id'] == u_id]['group_id'].values
        if len(user_groups) > 0:
            g_id = random.choice(user_groups)
            group_m = group_members_df[group_members_df['group_id'] == g_id]['user_id'].values
            senders = [m for m in group_m if m != u_id]
            sender_id = random.choice(senders) if len(senders) > 0 else random.choice(user_ids)
        else:
            conv_type = 'personal'
            
    if conv_type == 'business':
        user_biz = ubh_df[ubh_df['user_id'] == u_id]['business_id'].values
        if len(user_biz) > 0:
            b_id = random.choice(user_biz)
        else:
            conv_type = 'personal'
            
    if conv_type == 'personal':
        sender_id = random.choice([x for x in user_ids if x != u_id])
        
    created_at = (target_base_time + datetime.timedelta(minutes=idx * 5)).strftime("%Y-%m-%d %H:%M")
    category = random.choice(['scam', 'urgent', 'event', 'payment', 'promotion', 'greeting', 'forward', 'personal'])
    text = make_random_text(category)
    
    media_type = np.nan
    media_id = np.nan
    if random.random() > 0.8:
        media_type = random.choice(['image', 'voice'])
        media_id = f"img_{random.randint(100, 999)}" if media_type == 'image' else f"vn_{random.randint(100, 999)}"
        
    forwarded = random.randint(0, 10) if category == 'forward' else 0
    
    target_records.append({
        'message_id': m_id,
        'user_id': u_id,
        'conversation_type': conv_type,
        'group_id': g_id,
        'business_id': b_id,
        'sender_user_id': sender_id,
        'created_at': created_at,
        'message_text': text,
        'media_type': media_type,
        'media_id': media_id,
        'forwarded_count': forwarded
    })
    
    # Establish ground truth mapping
    action = 'digest'
    if category == 'scam':
        action = 'mute'
    elif category == 'urgent':
        action = 'notify'
    elif category == 'promotion':
        is_opt_out = False
        if conv_type == 'business' and b_id:
            biz_opts = ubh_df[(ubh_df['user_id'] == u_id) & (ubh_df['business_id'] == b_id)]
            if len(biz_opts) > 0 and biz_opts['allows_promotions'].values[0] == 0:
                is_opt_out = True
        action = 'mute' if is_opt_out else 'digest'
    elif category == 'personal':
        action = 'notify'
        
    ground_truth_records.append({
        'message_id': m_id,
        'action': action,
        'message_type': category
    })

target_df = pd.DataFrame(target_records)
ground_truth_df = pd.DataFrame(ground_truth_records)

# 9. Output blank template
output_df = pd.DataFrame({
    'message_id': target_ids,
    'action': [''] * target_rows,
    'message_type': [''] * target_rows,
    'reason': [''] * target_rows,
    'confidence': [''] * target_rows,
    'evidence_message_ids': [''] * target_rows
})

# Save to CSV files
users_df.to_csv(OUTPUT_DIR / "users.csv", index=False)
groups_df.to_csv(OUTPUT_DIR / "groups.csv", index=False)
group_members_df.to_csv(OUTPUT_DIR / "group_members.csv", index=False)
businesses_df.to_csv(OUTPUT_DIR / "business_accounts.csv", index=False)
ubh_df.to_csv(OUTPUT_DIR / "user_business_history.csv", index=False)
history_df.to_csv(OUTPUT_DIR / "message_history.csv", index=False)
events_df.to_csv(OUTPUT_DIR / "message_events.csv", index=False)
target_df.to_csv(OUTPUT_DIR / "messages.csv", index=False)
output_df.to_csv(OUTPUT_DIR / "output.csv", index=False)
ground_truth_df.to_csv(OUTPUT_DIR / "ground_truth.csv", index=False)

print(f"Large synthetic dataset successfully generated at {OUTPUT_DIR}!")
