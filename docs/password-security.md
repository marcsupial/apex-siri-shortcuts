# Your Apex password in Shortcuts

Each Apex shortcut needs your Apex's password, so the shortcut stores it. This page
covers where that password goes, what protects it at each step, and the practices
that actually matter.

The short version: storing it in the shortcut is reasonable, provided it's a password
you don't use anywhere else.

## Where the password goes

| Where | What protects it |
|---|---|
| **The shortcut on your devices** | Encrypted at rest along with the rest of your data: Apple devices give every file its own encryption key ([Apple Platform Security][data-protection]). Anyone who can open Shortcuts on your unlocked device can read it. |
| **iCloud, which syncs your shortcuts** | Encrypted in transit and on Apple's servers, with Apple holding the keys. With [Advanced Data Protection][icloud-security] turned on, shortcuts are end-to-end encrypted: "decrypted only on your trusted devices". |
| **Shortcuts you share** | Left out. The shortcut collects the password through an import question, and per Apple, a field with an import question "is cleared when the shortcut is shared" ([Shortcuts User Guide][import-questions]). |
| **Your home network** | Nothing. The Apex only accepts logins over plain HTTP, so the password crosses your network unencrypted every time the shortcut, or the Apex's own dashboard, logs in ([apex-local-api.md](apex-local-api.md)). |

The network is the weakest link, and no choice about where the shortcut keeps the
password changes that.

## What the password can do

It's the Apex's only local login, and it has full control. The dashboard's local
settings hold a single username and password; the View, Control and Owner roles in its
code belong to Apex Fusion's account sharing. The local API can only be reached from
your home network, as long as you haven't forwarded a port to the Apex.

So the realistic risks are someone on your network capturing the password, someone
using your unlocked phone or Mac, and the same password protecting something that
matters more.

## Best practices

1. **Use a password you don't use anywhere else.** This matters most, because the
   password travels unencrypted on your network. The Apex's dashboard accepts 4 to 15
   characters, so make them random rather than a word.
2. **Keep the password in the setup fields.** Those fields are cleared when you share
   the shortcut. A password typed anywhere else in a shortcut would go along with it.
3. **Keep one copy.** As more commands are added, the plan is one helper shortcut that
   holds the login, which the other shortcuts call with Run Shortcut. It's a
   [common pattern][thingelstad]: fewer copies to read, and one place to change it.
4. **Lock your devices.** Anyone using your unlocked phone or Mac can open the
   shortcut and read its setup fields.
5. **Consider Advanced Data Protection** if you want your shortcuts end-to-end
   encrypted in iCloud. It needs iOS 16.2 or macOS 13.1 or later
   ([Apple][icloud-security]), and it isn't available to new users in the UK
   ([Apple][adp-uk]). Read Apple's notes on account recovery before turning it on.
6. **Keep the Apex off the internet.** Forwarding a port to it would expose the
   password and every command to anyone who finds it.
7. **Keep passwords out of anything published.** For developers: this repo's shortcut
   files are public and signed for "Anyone", which sends Apple a copy for validation
   ([Shortcuts User Guide][share]), so their setup answers ship empty. (Signing for
   "People Who Know Me" would put your contact info in the file instead.) Scripts that
   need a real login read the password with a hidden prompt and print only redacted
   values.

## Stronger storage, and what it costs

- **Shortcuts has no keychain.** There's no action to store or read a secret in the
  keychain, and Apple's Passwords app offers no Shortcuts actions (checked on macOS 27).
- **Scriptable's keychain** keeps values "securely stored in an encrypted database"
  ([Scriptable docs][scriptable]), and a shortcut can read them through Scriptable.
  Its documentation doesn't say whether values sync between devices or can be read
  while the phone is locked, and it means installing Scriptable wherever the shortcut
  runs.
- **Asking for the password each time** keeps it out of storage, but you'd have to
  type it, which defeats voice control.
- **Encoding the password** (Base64, for example) only disguises it. Anyone who opens
  the shortcut can decode it.

## Not yet verified here

- That Shortcuts clears the setup fields when you share this project's shortcut.
  Apple documents it; it hasn't been tested with this shortcut.
- How Scriptable's keychain behaves across devices and with the phone locked.

Sources checked October 2026.

[data-protection]: https://support.apple.com/guide/security/data-protection-overview-secf6276da8a/web
[icloud-security]: https://support.apple.com/en-us/102651
[adp-uk]: https://support.apple.com/en-us/122234
[import-questions]: https://support.apple.com/guide/shortcuts/add-import-questions-to-shared-shortcuts-apdf330fd3a0/ios
[share]: https://support.apple.com/guide/shortcuts-mac/share-shortcuts-apdf01f8c054/mac
[scriptable]: https://docs.scriptable.app/keychain/
[thingelstad]: https://thingelstad.com/2020/04/21/using-api-credentials.html
