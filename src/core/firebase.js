// Firebase Integration Module
import { initializeApp } from 'firebase/app';
import {
    getAuth,
    signInWithEmailAndPassword,
    createUserWithEmailAndPassword,
    signInWithPopup,
    GoogleAuthProvider,
    onAuthStateChanged,
    signOut,
    setPersistence,
    browserLocalPersistence
} from 'firebase/auth';
import { getFirestore, doc, setDoc, getDoc, updateDoc } from 'firebase/firestore';

// Firebase state variables
let app;
let auth;
let db;
let currentUser = null;
let userProfile = null;
let isInitialized = false;

/**
 * Initialize Firebase by loading configuration from external file
 * @returns {Promise} Resolves when Firebase is initialized
 */
export async function initializeFirebase() {
    if (isInitialized) return true;

    try {
        // Firebase configuration embedded directly in code
        const firebaseConfig = {
            apiKey: "AIzaSyCI7ghBNffnJ_y0bL5-54U98bJMHAnRvxI",
            authDomain: "theboatgame-db51b.firebaseapp.com",
            projectId: "theboatgame-db51b",
            storageBucket: "theboatgame-db51b.firebasestorage.app",
            messagingSenderId: "162301964739",
            appId: "1:162301964739:web:aca5082057d041921a8d76",
            measurementId: "G-T7YK6HFWW7"
        };

        // Initialize Firebase services
        app = initializeApp(firebaseConfig);
        auth = getAuth(app);

        // Set persistence to LOCAL (persists indefinitely)
        await setPersistence(auth, browserLocalPersistence);
        console.log("Firebase persistence set to LOCAL");

        db = getFirestore(app);

        // Set up auth state listener
        onAuthStateChanged(auth, (user) => {
            currentUser = user;
            if (user) {
                console.log("User signed in:", user.displayName || user.email);
                loadUserProfile(user.uid);
            } else {
                console.log("User signed out");
                userProfile = null;
            }
        });

        isInitialized = true;
        console.log("Firebase initialized successfully");
        return true;
    } catch (error) {
        console.error("Error initializing Firebase:", error);
        return false;
    }
}

/**
 * Load user profile data from Firestore
 * @param {string} uid - User ID
 */
async function loadUserProfile(uid) {
    try {
        const userDoc = await getDoc(doc(db, "players", uid));
        if (userDoc.exists()) {
            console.log("User profile found:", userDoc.data());
            userProfile = userDoc.data();
        } else {
            // Create new profile if it doesn't exist
            console.log("User profile not found, creating new profile");
            userProfile = {
                displayName: currentUser.displayName || `Sailor ${Math.floor(Math.random() * 1000)}`,
                color: `#${Math.floor(Math.random() * 16777215).toString(16)}`,
                fishCount: 0,
                monsterKills: 0,
                money: 0,
                created: new Date()
            };
            await setDoc(doc(db, "players", uid), userProfile);
        }
        console.log("User profile loaded:", userProfile);

        // Dispatch event for other systems to react to
        window.dispatchEvent(new CustomEvent('userProfileLoaded', {
            detail: { profile: userProfile }
        }));

        return userProfile;
    } catch (error) {
        console.error("Error loading user profile:", error);
        return null;
    }
}

/**
 * Update user stats in Firestore
 * @param {Object} stats - Stats to update
 */
export async function updateUserStats(stats) {
    if (!currentUser || !userProfile) return;

    try {
        await updateDoc(doc(db, "players", currentUser.uid), stats);
        // Update local profile
        userProfile = { ...userProfile, ...stats };
        console.log("User stats updated:", stats);
    } catch (error) {
        console.error("Error updating user stats:", error);
    }
}

/**
 * Get current user profile
 * @returns {Object|null} User profile or null if not logged in
 */
export function getUserProfile() {
    return userProfile;
}

/**
 * Check if user is already signed in from a previous session
 * @returns {boolean} True if user is already signed in
 */
export function isUserSignedIn() {
    return !!currentUser;
}

/**
 * Show Firebase authentication popup
 * @param {Function} onSuccess - Callback when auth succeeds
 */
export function showAuthPopup(onSuccess) {
    if (!isInitialized) {
        console.error("Firebase not initialized");
        return;
    }

    // Check if user is already signed in from a previous session
    if (currentUser) {
        console.log("User already signed in from previous session");
        if (onSuccess && typeof onSuccess === 'function') {
            onSuccess(currentUser);
        }
        return;
    }

    // Remove any existing auth container
    const existingContainer = document.querySelector('.auth-container');
    if (existingContainer) {
        document.body.removeChild(existingContainer);
    }

    // Create and display authentication dialog
    const authContainer = document.createElement('div');
    authContainer.className = 'auth-container';
    authContainer.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background-color: rgba(0,0,0,0.7);
        display: flex;
        justify-content: center;
        align-items: center;
        z-index: 1000;
    `;

    const authForm = document.createElement('div');
    authForm.className = 'auth-form';
    authForm.style.cssText = `
        background-color: white;
        padding: 20px;
        border-radius: 5px;
        box-shadow: 0 0 10px rgba(0,0,0,0.5);
        width: 350px;
        max-width: 90%;
    `;

    authForm.innerHTML = `
        <h2 style="text-align: center; margin-bottom: 20px;">The Boat Game</h2>
        <div style="text-align: center; margin-bottom: 20px;">
            <button id="google-signin" style="
                background-color: white;
                color: #757575;
                border: 1px solid #dadce0;
                border-radius: 4px;
                padding: 10px 15px;
                display: flex;
                align-items: center;
                justify-content: center;
                width: 100%;
                cursor: pointer;
                font-family: 'Roboto', sans-serif;
                margin-bottom: 15px;
            ">
                <span style="margin-right: 10px;">
                    <svg width="18" height="18" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">
                        <path fill="#FFC107" d="M43.611,20.083H42V20H24v8h11.303c-1.649,4.657-6.08,8-11.303,8c-6.627,0-12-5.373-12-12c0-6.627,5.373-12,12-12c3.059,0,5.842,1.154,7.961,3.039l5.657-5.657C34.046,6.053,29.268,4,24,4C12.955,4,4,12.955,4,24c0,11.045,8.955,20,20,20c11.045,0,20-8.955,20-20C44,22.659,43.862,21.35,43.611,20.083z"></path>
                        <path fill="#FF3D00" d="M6.306,14.691l6.571,4.819C14.655,15.108,18.961,12,24,12c3.059,0,5.842,1.154,7.961,3.039l5.657-5.657C34.046,6.053,29.268,4,24,4C16.318,4,9.656,8.337,6.306,14.691z"></path>
                        <path fill="#4CAF50" d="M24,44c5.166,0,9.86-1.977,13.409-5.192l-6.19-5.238C29.211,35.091,26.715,36,24,36c-5.202,0-9.619-3.317-11.283-7.946l-6.522,5.025C9.505,39.556,16.227,44,24,44z"></path>
                        <path fill="#1976D2" d="M43.611,20.083H42V20H24v8h11.303c-0.792,2.237-2.231,4.166-4.087,5.571c0.001-0.001,0.002-0.001,0.003-0.002l6.19,5.238C36.971,39.205,44,34,44,24C44,22.659,43.862,21.35,43.611,20.083z"></path>
                    </svg>
                </span>
                Sign in with Google
            </button>
        </div>
        
        <div style="margin-bottom: 15px;">
            <input type="email" id="email" placeholder="Email" style="width: 100%; padding: 8px; margin-bottom: 10px; box-sizing: border-box;">
            <input type="password" id="password" placeholder="Password" style="width: 100%; padding: 8px; box-sizing: border-box;">
        </div>
        
        <div style="display: flex; gap: 10px;">
            <button id="signin-btn" style="flex: 1; padding: 10px; background-color: #3498db; color: white; border: none; border-radius: 4px; cursor: pointer;">Sign In</button>
            <button id="signup-btn" style="flex: 1; padding: 10px; background-color: #2ecc71; color: white; border: none; border-radius: 4px; cursor: pointer;">Sign Up</button>
        </div>
        
        <div id="auth-error" style="color: red; margin-top: 10px; text-align: center;"></div>
    `;

    authContainer.appendChild(authForm);
    document.body.appendChild(authContainer);

    // Auth error display
    const showError = (message) => {
        document.getElementById('auth-error').textContent = message;
    };

    // Google Sign In
    document.getElementById('google-signin').addEventListener('click', async () => {
        try {
            const provider = new GoogleAuthProvider();
            const result = await signInWithPopup(auth, provider);
            authSuccess(result.user);
        } catch (error) {
            showError(error.message);
            console.error("Google sign-in error:", error);
        }
    });

    // Email/Password Sign In
    document.getElementById('signin-btn').addEventListener('click', async () => {
        const email = document.getElementById('email').value;
        const password = document.getElementById('password').value;

        if (!email || !password) {
            showError('Please enter both email and password');
            return;
        }

        try {
            const result = await signInWithEmailAndPassword(auth, email, password);
            authSuccess(result.user);
        } catch (error) {
            showError(error.message);
            console.error("Sign-in error:", error);
        }
    });

    // Email/Password Sign Up
    document.getElementById('signup-btn').addEventListener('click', async () => {
        const email = document.getElementById('email').value;
        const password = document.getElementById('password').value;

        if (!email || !password) {
            showError('Please enter both email and password');
            return;
        }

        if (password.length < 6) {
            showError('Password must be at least 6 characters');
            return;
        }

        try {
            const result = await createUserWithEmailAndPassword(auth, email, password);
            authSuccess(result.user);
        } catch (error) {
            showError(error.message);
            console.error("Sign-up error:", error);
        }
    });

    // Success handler
    function authSuccess(user) {
        // Close the auth popup
        document.body.removeChild(authContainer);

        // Call the success callback if provided
        if (onSuccess && typeof onSuccess === 'function') {
            onSuccess(user);
        }
    }
}

/**
 * Sign out the current user
 */
export function signOutUser() {
    if (auth) signOut(auth);
}

/**
 * Get hex color from user profile or generate one
 * @returns {string} Hex color code
 */
export function getUserColor() {
    if (userProfile && userProfile.color) {
        return userProfile.color;
    }
    return `#${Math.floor(Math.random() * 16777215).toString(16)}`;
}

/**
 * Get username from user profile or generate one
 * @returns {string} Username
 */
export function getUsername() {
    if (userProfile && userProfile.displayName) {
        return userProfile.displayName;
    }
    if (currentUser && currentUser.displayName) {
        return currentUser.displayName;
    }
    return `Sailor ${Math.floor(Math.random() * 1000)}`;
} 