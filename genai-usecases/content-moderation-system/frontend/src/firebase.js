import { initializeApp } from 'firebase/app';
import { 
  getAuth, 
  signInWithEmailAndPassword, 
  createUserWithEmailAndPassword, 
  signOut,
  onAuthStateChanged,
  getIdToken
} from 'firebase/auth';
import { getFirestore } from 'firebase/firestore';

// Firebase configuration for project finalyearproject-ae788
const firebaseConfig = {
  apiKey: "AIzaSyA6BnQnoFTKnQrnxDgWGQMqETDxrSiHC9o",
  authDomain: "finalyearproject-ae788.firebaseapp.com",
  projectId: "finalyearproject-ae788",
  storageBucket: "finalyearproject-ae788.firebasestorage.app",
  messagingSenderId: "90575036528",
  appId: "1:90575036528:web:32b599c373e33e0c0194b5",
  measurementId: "G-5N7S43E8PG"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
export const db = getFirestore(app);

export {
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signOut,
  onAuthStateChanged,
  getIdToken
};

export default app;
