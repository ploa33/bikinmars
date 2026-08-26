# 🚀 Guide de configuration Supabase pour BikinMars

Ce guide vous explique comment configurer votre base de données Supabase gratuite et l'associer à votre dépôt GitHub en moins de 3 minutes.

---

### Étape 1 : Créer un projet Supabase gratuit
1. Rendez-vous sur **[supabase.com](https://supabase.com)** et connectez-vous (avec votre compte GitHub).
2. Cliquez sur **"New Project"**.
3. Donnez un nom (ex: `bikinmars-db`), choisissez un mot de passe et sélectionnez la région la plus proche (**Paris (EU West 3)** ou **Frankfurt**).

---

### Étape 2 : Exécuter le schéma SQL
1. Dans votre tableau de bord Supabase, cliquez sur l'onglet **SQL Editor** dans le menu de gauche.
2. Cliquez sur **"New query"**.
3. Copiez-collez l'intégralité du contenu du fichier [`supabase/schema.sql`](./schema.sql) et cliquez sur **"Run"** (ou Ctrl+Entrée).
4. ✅ Toutes les tables (`stations`, `bikes`, `active_trips`, `completed_trips`), les index et la vue `vw_bikes_health` sont créées !

---

### Étape 3 : Configurer les Secrets GitHub Actions
1. Dans Supabase, allez dans **Project Settings** (icône d'engrenage en bas à gauche) $\rightarrow$ **API**.
2. Récupérez :
   - **Project URL** (ex: `https://xyzabcdef.supabase.co`)
   - **Project API Keys** $\rightarrow$ clé **`service_role`** (cliquez sur "Reveal" — cette clé permet au script d'écrire dans la base).
   - **Project API Keys** $\rightarrow$ clé **`anon`** (clé publique pour la lecture sur le site web).
3. Rendez-vous sur votre dépôt GitHub : **Settings** $\rightarrow$ **Secrets and variables** $\rightarrow$ **Actions**.
4. Ajoutez les 2 secrets suivants :
   - Nom : `SUPABASE_URL` | Valeur : *votre Project URL*
   - Nom : `SUPABASE_SERVICE_ROLE_KEY` | Valeur : *votre clé service_role*

---

### Étape 4 : Lancer le Tracker !
- Rendez-vous sur l'onglet **Actions** de votre dépôt GitHub.
- Cliquez sur **"Levélo Live Trip Tracker & Supabase Sync"** $\rightarrow$ **"Run workflow"**.
- Le scraper va se lancer immédiatement et s'exécutera automatiquement toutes les 5 minutes 24h/24 !
