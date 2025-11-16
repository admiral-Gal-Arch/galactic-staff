# app.py

import streamlit as st
import pymongo
import pandas as pd
import streamlit_authenticator as stauth
from pymongo.server_api import ServerApi
from bson import ObjectId
import os

# --- Page Configuration ---
st.set_page_config(
    page_title="Galactic Support Center",
    page_icon="🛰️",
    layout="wide"
)

# --- 1. MongoDB Connection ---

@st.cache_resource
def init_connection():
    """Initialize a connection to MongoDB Atlas."""
    try:
        uri = os.environ.get("MONGO_URI")
        if not uri:
            st.error("MONGO_URI environment variable not set.")
            return None
            
        client = pymongo.MongoClient(uri, server_api=ServerApi('1'))
        client.admin.command('ping')
        return client
    except Exception as e:
        st.error(f"Failed to connect to MongoDB: {e}")
        return None

client = init_connection()

if client is None:
    st.stop()

@st.cache_resource
def get_database(db_name):
    return client[db_name]

@st.cache_resource
def get_collection(db_name, collection_name):
    db = get_database(db_name)
    return db[collection_name]

# --- Get your collections ---
staff_collection = get_collection("support_center", "staff_users")
tickets_collection = get_collection("support_center", "tickets")


# --- 2. User Authentication ---

@st.cache_data(ttl=600)
def fetch_all_users():
    """Fetch all staff users from the database."""
    try:
        return list(staff_collection.find({}, {"_id": 0}))
    except Exception as e:
        st.error(f"Error fetching user data: {e}")
        return []

users = fetch_all_users()

if not users:
    st.error("No staff users found in the database. Please add a user.")
    st.stop()

credentials = {
    "usernames": {
        user["username"]: {
            "name": user["name"],
            "email": user["email"],
            "password": user["password"]
        }
        for user in users
    }
}

# --- Initialize the Authenticator ---
try:
    authenticator = stauth.Authenticate(
        credentials,
        os.environ.get("STAFF_COOKIE_NAME"),
        os.environ.get("STAFF_COOKIE_KEY"),
        int(os.environ.get("STAFF_COOKIE_EXPIRY", 7)) 
    )
except Exception as e:
    st.error(f"Error initializing authenticator: {e}. Check cookie environment variables.")
    st.stop()


# --- 3. View Management (Session State) ---
if "view" not in st.session_state:
    st.session_state.view = "dashboard"
if "selected_ticket_id" not in st.session_state:
    st.session_state.selected_ticket_id = None
if "authentication_status" not in st.session_state:
    st.session_state.authentication_status = None
if "name" not in st.session_state:
    st.session_state.name = None


# --- 4. Main Application Logic (UPDATED) ---

# --- THIS IS THE FIX ---
# Add 'or (None, None, None)' to provide a default value
name, authentication_status, username = authenticator.login() or (None, None, None)


# Now, check the session state that the widget just updated.
if st.session_state.authentication_status:
    # --- LOGGED-IN VIEW ---
    st.sidebar.title(f"Welcome, *{st.session_state.name}*")
    authenticator.logout('Logout', 'sidebar')

    staff_name_list = [user["name"] for user in users]

    if st.session_state.view == "dashboard":
        show_dashboard(staff_name_list)
    elif st.session_state.view == "detail":
        show_ticket_detail(st.session_state.selected_ticket_id, staff_name_list)

elif st.session_state.authentication_status == False:
    # --- LOGIN FAILED ---
    st.error('Username/password is incorrect')

elif st.session_state.authentication_status == None:
    # --- DEFAULT LOGIN VIEW ---
    # The login form is already on the page (from authenticator.login())
    pass


# --- 5. Dashboard and Detail Functions (Unchanged) ---
# ... (all the function definitions from before) ...

def show_dashboard(staff_list):
    st.title("🛰️ Support Center Dashboard")
    st.write("Select a ticket from the queue to view and edit details.")

    @st.cache_data(ttl=60)
    def get_all_tickets():
        try:
            tickets = list(tickets_collection.find({}, {}))
            if not tickets:
                return pd.DataFrame(columns=["_id", "status", "subject", "user_email", "created_at", "assigned_to"])
            
            df = pd.DataFrame(tickets)
            df["_id"] = df["_id"].astype(str)
            return df
        except Exception as e:
            st.error(f"Error fetching tickets: {e}")
            return pd.DataFrame()

    df_tickets = get_all_tickets()

    if df_tickets.empty:
        st.success("No open tickets! 🚀")
        return

    st.sidebar.header("Filter Tickets")
    
    if "status" not in df_tickets.columns: df_tickets["status"] = "Unknown"
    if "assigned_to" not in df_tickets.columns: df_tickets["assigned_to"] = None

    status_options = ["All"] + list(df_tickets["status"].fillna("Unknown").unique())
    assignee_list = ["Unassigned"] + staff_list
    assignee_options = ["All"] + list(pd.Series(assignee_list).unique())

    selected_status = st.sidebar.selectbox("Filter by Status:", status_options)
    selected_assignee = st.sidebar.selectbox("Filter by Assignee:", assignee_options)

    filtered_df = df_tickets.copy()

    if selected_status != "All":
        filtered_df = filtered_df[filtered_df["status"].fillna("Unknown") == selected_status]

    if selected_assignee == "Unassigned":
        filtered_df = filtered_df[filtered_df["assigned_to"].isna() | (filtered_df["assigned_to"] == "")]
    elif selected_assignee != "All":
        filtered_df = filtered_df[filtered_df["assigned_to"] == selected_assignee]

    st.dataframe(
        filtered_df,
        key="ticket_queue",
        on_select="rerun",
        selection_mode="single-row",
        use_container_width=True,
        column_order=("_id", "status", "subject", "user_email", "created_at", "assigned_to"),
        column_config={
            "_id": "Ticket ID",
            "status": "Status",
            "subject": "Ticket Subject",
            "user_email": "User Email",
            "created_at": "Date Created",
            "assigned_to": "Assigned To"
        },
        hide_index=True
    )
    
    if st.session_state.ticket_queue.selection.rows:
        selected_row_index = st.session_state.ticket_queue.selection.rows[0]
        selected_id = filtered_df.iloc[selected_row_index]["_id"]
        
        st.session_state.selected_ticket_id = selected_id
        st.session_state.view = "detail"
        st.rerun()


def show_ticket_detail(ticket_id, staff_list):
    
    if st.button("← Back to Dashboard"):
        st.session_state.view = "dashboard"
        st.session_state.selected_ticket_id = None
        st.rerun()

    st.title("Manage Ticket Details")
    st.markdown(f"**Ticket ID:** `{ticket_id}`")

    try:
        current_ticket = tickets_collection.find_one({"_id": ObjectId(ticket_id)})
    except Exception as e:
        st.error(f"Could not find ticket. Error: {e}")
        return

    if not current_ticket:
        st.error("Ticket not found.")
        return

    st.subheader("Ticket Information")
    col1, col2 = st.columns(2)
    col1.metric("Status", current_ticket.get("status", "N/A"))
    col2.metric("Submitted By", current_ticket.get("user_email", "N/A"))
    
    st.text_input("Subject", current_ticket.get("subject", ""), disabled=True)
    st.text_area("Full Description", current_ticket.get("description", ""), height=150, disabled=True)
    
    st.divider()
    
    st.subheader("Support Actions")
    
    current_status = current_ticket.get("status", "New")
    current_assignee = current_ticket.get("assigned_to")
    current_notes = current_ticket.get("internal_notes", "")

    status_options = ["New", "In Progress", "Awaiting User", "Closed"]
    if current_status not in status_options:
        status_options.append(current_status)
        
    assignee_options = ["Unassigned"] + staff_list
    
    try:
        status_index = status_options.index(current_status)
    except ValueError: status_index = 0
        
    try:
        assignee_index = assignee_options.index(current_assignee if current_assignee else "Unassigned")
    except ValueError: assignee_index = 0

    with st.form("update_ticket_form"):
        new_status = st.selectbox("Update Status", options=status_options, index=status_index)
        new_assignee = st.selectbox("Assign To", options=assignee_options, index=assignee_index)
        new_notes = st.text_area("Add Internal Notes (new notes will be prepended)", value="", placeholder="Type your update here...")
        submitted = st.form_submit_button("Save Changes")

    if submitted:
        final_assignee = None if new_assignee == "Unassigned" else new_assignee
        
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        note_entry = f"--- Update by {st.session_state.name} ({now}) ---\n{new_notes}\n\n"
        
        final_notes = note_entry + current_notes if new_notes.strip() else current_notes

        try:
            tickets_collection.update_one(
                {"_id": ObjectId(ticket_id)},
                {
                    "$set": {
                        "status": new_status,
                        "assigned_to": final_assignee,
                        "internal_notes": final_notes
                    }
                }
            )
            st.success("Ticket updated successfully!")
            get_all_tickets.clear()
            st.session_state.view = "dashboard"
            st.session_state.selected_ticket_id = None
            st.rerun()

        except Exception as e:
            st.error(f"Failed to update ticket: {e}")
