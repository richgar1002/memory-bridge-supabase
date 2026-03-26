# 🧠 Memory Bridge - Production RLS

## ⚠️ Important: Enable Production Security

Before going to production, enable Row-Level Security (RLS) to protect user data.

---

## Environment Variables

Create a `.env` file (copy from `.env.example`) with these required variables:

```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key
```

### API Authentication

The API now requires JWT Bearer token authentication:

```bash
# Login to get token
curl -X POST https://your-api.com/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "password"}'

# Use token in requests
curl https://your-api.com/memories \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

### Security Changes Made

1. Removed hardcoded Supabase keys from `embeddings.py`
2. Replaced weak header-based auth with proper JWT validation
3. Added `/auth/login` and `/auth/signup` endpoints
4. Search now uses PostgreSQL FTS instead of client-side filtering

---

## Run Production RLS

Copy the contents of `rls_production.sql` and run it in Supabase SQL Editor.

### What This Does

1. **Enables RLS** on all tables
2. **Creates policies** so users can only see their own data:
   - `profiles` - users see own profile
   - `collections` - users see own collections
   - `memories` - users see own memories
   - `memory_embeddings` - users see own embeddings

3. **Adds search function** that respects user isolation

---

## Authentication Required

After enabling RLS, you MUST authenticate:

### Option 1: Sign Up
```python
from client_complete import create_memory_client

client = create_memory_client(
    supabase_url="https://your-project.supabase.co",
    supabase_key="your-anon-key"
)

# Sign up
user = client.supabase.auth.sign_up({
    "email": "user@example.com",
    "password": "password123"
})

# The user ID is now linked to memories
```

### Option 2: Sign In
```python
# Sign in
user = client.supabase.auth.sign_in({
    "email": "user@example.com", 
    "password": "password123"
})
```

---

## API Keys

| Key Type | Use | Auth Required |
|---------|-----|----------------|
| `anon` public | Client-side | Yes |
| `service_role` | Server/admin | No (bypass RLS) |

### For Production:
- Use `anon` key in your app
- Users must sign in to access their data
- Never expose `service_role` in client code

---

## How It Works

```
User signs up/login
       ↓
auth.users table gets user
       ↓
Memories linked to user_id
       ↓
RLS policies filter:
  "SELECT * FROM memories 
   WHERE user_id = auth.uid()"
       ↓
User only sees their data ✅
```

---

## Test RLS

After enabling, verify:

1. Sign up a user
2. Create a memory
3. Try to query as anonymous - should fail
4. Try to query as different user - should see only their own

---

## Rollback

If you need to disable RLS:
```sql
ALTER TABLE public.profiles DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.collections DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.memories DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.memory_embeddings DISABLE ROW LEVEL SECURITY;
```

⚠️ **Warning:** This allows anyone to see all data!

---

## Production Checklist

- [ ] Run `rls_production.sql`
- [ ] Test authentication flow
- [ ] Verify user isolation works
- [ ] Use `anon` key in client
- [ ] Never expose `service_role` in frontend
