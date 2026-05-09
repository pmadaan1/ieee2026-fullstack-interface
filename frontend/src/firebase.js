// Firebase Web SDK setup + Firestore query helpers for the long-term view.
//
// Setup (in this directory's parent):
//   1. cd frontend && npm install firebase
//   2. Create frontend/.env.local with the values from your Firebase project's
//      web app config (Project Settings → General → Your apps → SDK setup):
//
//        REACT_APP_FIREBASE_API_KEY=...
//        REACT_APP_FIREBASE_AUTH_DOMAIN=...
//        REACT_APP_FIREBASE_PROJECT_ID=...
//        REACT_APP_FIREBASE_STORAGE_BUCKET=...
//        REACT_APP_FIREBASE_MESSAGING_SENDER_ID=...
//        REACT_APP_FIREBASE_APP_ID=...
//
//      These are public/safe — Firebase API keys are project identifiers,
//      not secrets. Security comes from Firestore rules, not the key.
//   3. Restart `npm start`.
//
// Without these env vars set, isFirebaseEnabled() returns false and
// fetchMinutes() resolves to []. The live view stays fully functional.

import { initializeApp } from 'firebase/app';
import {
  getFirestore, collection, query, where, orderBy, limit, getDocs,
} from 'firebase/firestore';

const config = {
  apiKey:            process.env.REACT_APP_FIREBASE_API_KEY,
  authDomain:        process.env.REACT_APP_FIREBASE_AUTH_DOMAIN,
  projectId:         process.env.REACT_APP_FIREBASE_PROJECT_ID,
  storageBucket:     process.env.REACT_APP_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: process.env.REACT_APP_FIREBASE_MESSAGING_SENDER_ID,
  appId:             process.env.REACT_APP_FIREBASE_APP_ID,
};

const enabled = !!(config.apiKey && config.projectId);
let db = null;
if (enabled) {
  const app = initializeApp(config);
  db = getFirestore(app);
}

export const DEFAULT_UID = 'demo-user';

export function isFirebaseEnabled() {
  return enabled;
}

/** Read minute docs for a uid in [sinceMs, nowMs]. Returns oldest→newest. */
export async function fetchMinutes(uid, sinceMs, maxDocs = 5000) {
  if (!enabled) return [];
  const ref = collection(db, 'users', uid, 'minutes');
  const q = query(
    ref,
    where('ts_ms', '>=', sinceMs),
    orderBy('ts_ms', 'asc'),
    limit(maxDocs),
  );
  const snap = await getDocs(q);
  return snap.docs.map(d => d.data());
}
