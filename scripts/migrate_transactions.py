import os
import pandas as pd
import firebase_admin
from firebase_admin import credentials, auth, firestore

# Firebase setup
if not firebase_admin._apps:
    cred = credentials.Certificate("firebase-service-account.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Local transaction file
FILE_NAME = "raw-transactions.pkl"

# Email-to-user_name mapping
email_to_user = {
    "eriktuck@gmail.com": "erik",
    "rsurvil@gmail.com": "rachel"
}

def read_transactions(file_name=FILE_NAME):
    return pd.read_pickle(os.path.join("data", file_name))

def process_transactions(df, config):
    category_names = config["cat_names"]
    csp_from_group = config["csp_from_group"]
    csp_from_category = config["csp_from_category"]
    csp_labels = config["csp_labels"]
    drop_cats = config["drop_cats"]
    
    # Assign labels
    df["category_group"] = df["category_name"].map(category_names)
    df = df.assign(
        csp_from_group=df["category_group"].map(csp_from_group),
        csp_from_category=df["category_name"].map(csp_from_category),
        csp=lambda x: x["csp_from_group"].fillna(x["csp_from_category"]).fillna("guilt_free"),
        csp_label=lambda x: x["csp"].map(csp_labels)
    )

    # Drop transactions
    df = df.loc[~df["category_name"].isin(drop_cats) & ~df["hideFromReports"]]

    return df


def find_household_for_user(uid):
    households_ref = db.collection("households")
    query = households_ref.where("members", "array_contains", uid).limit(1)
    docs = query.stream()
    
    for doc in docs:
        return doc.id  # first (and only) match
    
    return None



def main():
    transactions_df = read_transactions()
    transactions_df["category_name"] = transactions_df["category"].apply(lambda x: x["name"])
    transactions_df["account_name"] = transactions_df["account"].apply(lambda x: x["displayName"])

    users_ref = db.collection("users")

    for email, user_key in email_to_user.items():
        try:
            uid = auth.get_user_by_email(email).uid
        except:
            print(f"Skipping {email} - no UID found.")
            continue

        user_doc = users_ref.document(uid).get()
        if not user_doc.exists:
            print(f"User document for {email} not found.")
            continue

        config = user_doc.to_dict()

        household_id = find_household_for_user(uid)
        if not household_id:
            print(f"No household found for user {user_key} ({email})")
            continue

        # Process and upload transactions for users
        filt = transactions_df['account_name'].isin(config['accounts'])
        user_txns = transactions_df.loc[filt].copy()

        user_txns = process_transactions(user_txns, config)
        user_txns_dict = user_txns.drop(columns=["category", "account", "merchant"]).to_dict(orient="records")

        print(f"Uploading {len(user_txns_dict)} transactions for {user_key}...")
        batch = db.batch()
        for txn in user_txns_dict:
            txn_id = txn["id"]
            doc_ref = db.collection("users").document(uid).collection("transactions").document(str(txn_id))
            batch.set(doc_ref, txn)
        batch.commit()
        print(f"Done uploading for {user_key}.")

    # Process and upload transactions for joint household
    household_ref = db.collection("households")
    household_doc = household_ref.document(household_id).get()
    config = household_doc.to_dict()

    filt = transactions_df['account_name'].isin(config['accounts'])
    hh_txns = transactions_df.loc[filt].copy()

    hh_txns = process_transactions(hh_txns, config)
    hh_txns_dict = hh_txns.drop(columns=["category", "account", "merchant"]).to_dict(orient="records")

    print(f"Uploading {len(hh_txns_dict)} transactions for {household_id}...")
    batch = db.batch()
    for txn in hh_txns_dict:
        txn_id = txn["id"]
        doc_ref = db.collection("households").document(household_id).collection("transactions").document(str(txn_id))
        batch.set(doc_ref, txn)
    batch.commit()
    print(f"Done uploading for {household_id}.")

if __name__ == "__main__":
    main()
