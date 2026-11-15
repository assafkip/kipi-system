# Malware analysis and attribution toolkit (for Sancho, static-first QC)

Research date: 2026-11-15. Maintenance status was checked live against the GitHub API (`archived`, last push) and PyPI (latest release date) on that day, and Homebrew availability with `brew info`. "Last push" is repo activity, not a release.

Legend, per bullet: **Tool**: what. **When**: trigger. **S/D** (S = static, never executes the sample; D = executes or emulates, founder-gated for Sancho). **Cost**. **Install** (macOS).
Status flags: **[ABANDONED]** = archived or no meaningful activity in 2+ years. **[STALE]** = works but slow or old releases. **[UNVERIFIED]** = could not confirm status.

Sancho's boundary, applied to every phase:
- S tools are always allowed.
- D tools (phase 5, plus emulators anywhere) need founder approval per case.
- Any tool that queries a live attacker host is out. Lookups to third-party intel services (VT hash search, MalwareBazaar, crt.sh, passive DNS, a public blockchain RPC) are not contact with attacker infrastructure. Uploading a file to them is a disclosure decision (see phase 6).

---

## 1. Triage and identification

- **file / libmagic**: file type from magic bytes. When: first command on any unknown blob. S. Free. `brew install libmagic` (`file` ships with macOS).
- **Detect It Easy (DiE, diec CLI)**: file type, compiler, linker, packer, protector and installer detection via scriptable signatures. Successor to PEiD as the default packer ID. When: right after `file`, before choosing a disassembler or unpacker. S. Free (MIT). Install: release DMG/zip from GitHub (no brew formula found). Very active (push 2026-11-15).
- **PEiD**: legacy packer ID. **[ABANDONED]**, signatures frozen around 2011. Use DiE.
- **ExeinfoPE**: Windows GUI packer/compiler ID with unpack hints. When: second opinion when DiE says "unknown". S. Free. Windows only. **[UNVERIFIED]**: the GitHub repo found (exeinfope/exeinfope) shows recent pushes but 0 stars, so it may not be the author's official channel.
- **hashing (shasum, md5)**: identity hashes for the evidence chain and intel lookups. When: on ingest, before anything else. S. Free. Built in.
- **ssdeep**: context-triggered piecewise fuzzy hash. When: clustering variants, "is this the same family as X". S. Free. `brew install ssdeep`; pure-Python alternative `pip install ppdeep` (2026). The `ssdeep` PyPI binding is **[STALE]** (2019).
- **TLSH**: locality-sensitive hash, more robust than ssdeep on small edits; VT and MalwareBazaar index it. When: variant clustering and pivoting in MalwareBazaar. S. Free. `pip install py-tlsh` (5.0.0, 2026). The old `python-tlsh` package is **[STALE]** (2021).
- **imphash / rich header hash**: hash of the PE import table / Rich header; clusters builds from one toolchain. When: PE pivoting in VT/MalwareBazaar. S. Free. via `pefile` (`pe.get_imphash()`).
- **YARA / YARA-X**: pattern rules over files and memory. YARA-X is VirusTotal's Rust rewrite and the future default; classic YARA is still maintained. When: matching known families, retro-hunting, and later shipping detections. S. Free. `brew install yara yara-x`; `pip install yara-python yara-x`.
- **capa (Mandiant FLARE)**: maps code features to capabilities and ATT&CK/MBC (for example "encrypt data using RC4", "compiled with .NET AoT"). When: right after packer ID, to know what the binary can do before opening a disassembler. S. Free. `pip install flare-capa` (10.0.0, 2026-10). Has a rule that flags .NET Native AOT.
- **FLOSS (Mandiant FLARE)**: extracts static, stack, tight and decoded strings; Go and Rust aware. When: whenever plain `strings` looks thin or obfuscated. S by default (it emulates decoding routines with vivisect; that is emulation of code fragments, not running the sample. Flag it to the founder if the case rules treat any emulation as gated). Free. `pip install flare-floss` (3.2.0, 2026-10).
- **strings**: ASCII and UTF-16 strings. When: always, early. S. Free. Built in (`strings -a`, plus `strings -el` style via FLOSS for UTF-16).
- **pefile**: Python PE parser (headers, sections, imports, resources, imphash). When: scripting PE triage and timestamps. S. Free. `pip install pefile` (last release 2024-08; repo active 2026-11).
- **LIEF**: parse and modify PE, ELF, Mach-O, plus DEX/OAT. When: cross-format parsing, Mach-O samples, scripted section dumps. S. Free. `pip install lief` (1.0.0, 2026-07) or `brew install lief`.
- **PE-bear (hasherezade)**: GUI PE viewer/editor, good for broken or manually unpacked PEs. When: hand-inspecting headers, fixing a dumped PE. S. Free. Release builds on GitHub (macOS build available). Active.
- **pestudio (Winitor)**: Windows GUI PE triage with indicator scoring. When: quick Windows-side triage. S. Free and paid Pro. Windows only. **[UNVERIFIED]** current release cadence.
- **XPEViewer / Manalyze**: alternative PE viewers/static analyzers. When: second opinion. S. Free. GitHub releases (both active 2026).
- **binwalk**: finds embedded files and firmware sections. When: blobs, firmware, overlays. S (extraction only). Free. `brew install binwalk`.
- **Binary Refinery (binref)**: composable CLI units for carving, decoding, decrypting, unpacking. When: scripted static decoding pipelines. S. Free. `pip install binary-refinery` (2026-10).
- **dotnetfile / dnfile**: Python .NET header and metadata parsers. When: .NET triage at scale. S. Free. `pip install dotnetfile dnfile`.

## 2. Unpacking

- **UPX**: `upx -d` restores UPX-packed binaries. When: DiE says UPX. Note: actors often corrupt UPX headers (`UPX!` magic renamed); fix the magic then retry. S. Free. `brew install upx`.
- **Static handling of custom packers** (the analyst's static path):
  - Find the decryption or decompression stub in a disassembler, identify the algorithm (capa, FLOSS, crypto constants via the findcrypt or `signsrch` style scripts), and reimplement it in Python or Binary Refinery or CyberChef against the embedded blob.
  - Carve the payload from resources, overlay or a high-entropy section (DiE entropy view, pefile).
  - Use known unpackers for public packers (for example NETReactorSlayer for .NET Reactor, de4dot forks, autoit-ripper).
- **UnpacMe (OALabs)**: automated unpacking service. When: a commodity packer needs fast unpacking. **D** (executes server side) and uploads the file. Free tier and paid. Web/API. Disclosure decision.
- **unipacker**: emulation-based Windows unpacker (Unicorn). When: emulation is approved and the packer is generic. **D** (emulation). Free. `pip install unipacker` **[STALE]** (2024-05 release).
- **mal_unpack / PE-sieve / HollowsHunter (hasherezade)**: dynamic unpackers that dump implants from a running process. When: sandbox phase only. **D**. Free. Windows only. Active.
- **Scylla / ScyllaHide**: import reconstruction and anti-anti-debug for x64dbg dumps. **D**. Free. Windows only. **[STALE]** (2023/2024).

## 3. Disassembly and decompilation

General-purpose:
- **Ghidra (NSA)**: disassembler/decompiler, scriptable, many plugins. When: default free decompiler for any native binary. S. Free. `brew install ghidra` (needs a JDK). 
- **IDA Free / Home / Pro (Hex-Rays)**: industry reference disassembler; Free has a cloud x86/x64 decompiler for non-commercial use; Pro has local decompilers for all architectures plus Lumina. When: the deep reversing seat; most published plugins target IDA. S. Free tier (non-commercial) and paid. Download installer from hex-rays.com.
- **Binary Ninja (Vector 35)**: disassembler with strong IL and API; WARP signature system. When: scripting-heavy work, NativeAOT via WARP. S. Free tier (non-commercial, limited), paid Personal/Commercial. Download from binary.ninja.
- **radare2 / rizin / Cutter**: open-source CLI RE frameworks; Cutter is rizin's GUI with the Ghidra decompiler plugin. When: scripting, quick CLI checks, no-license environments. S. Free. `brew install radare2 rizin cutter`.
- **BinDiff (Google)**: binary diffing. When: comparing two variants or builds. S. Free. Download from GitHub releases.
- **HashDB (OALabs)**: API-hash lookup service plus IDA plugin. When: shellcode or loaders that resolve APIs by hash. S (lookup service sees only hash values). Free. IDA plugin from GitHub.

.NET (managed, IL present):
- **dnSpyEx**: maintained fork of dnSpy; .NET decompiler, editor and debugger. When: any .NET assembly. S for decompile; **D** if you use its debugger. Free. Windows (runs in a VM). Active (2026-11).
- **ILSpy**: .NET decompiler (cross-platform via AvaloniaILSpy, plus `ilspycmd`). When: .NET on macOS, or batch decompile. S. Free. `brew install --cask ilspy`; `dotnet tool install -g ilspycmd`.
- **de4dot**: .NET deobfuscator/unpacker. **[ABANDONED]**: archived 2020 (de4dot-cex also archived). Community forks still circulate; quality varies. When: ConfuserEx, older obfuscators. S (mostly; some modes invoke the assembly's own decryptor, which is execution, so check per mode). Free.
- **NETReactorSlayer**: deobfuscator for .NET Reactor. When: DiE says .NET Reactor. S. Free. Active (2026-09).
- **EazFixer**: Eazfuscator.NET string and resource fixer. S (uses reflection on the sample in some paths; treat as D if so). Free. Active (2026-01).
- **AsmResolver (Washi)**: .NET and PE read/write library; base for custom static deobfuscators. S. Free. NuGet.

.NET NativeAOT (no IL, no CLR metadata; most .NET tools fail) - see summary at end of this phase:
- **Detection**: no CLR header; a `.managed` section, a single export `DotNetRuntimeDebugHeader`, an `RTR\0` ReadyToRun directory, and a .NET version string with commit hash in the binary (HarfangLab). capa has a rule "compiled with .NET AoT". HarfangLab published a YARA rule `NET_AOT`. S. Free.
- **ghidra-nativeaot (Washi1337)**: the original Ghidra analyzer. Parses the ReadyToRun directory, simulates the dehydration opcodes to rebuild the metadata statically, recovers MethodTables, the type hierarchy (base types, interfaces), vtables, and frozen string literals. When: any NativeAOT sample in Ghidra. S. Free. GitHub release zip. Active (push 2026-06). Limits: needs `__ReadyToRunHeader` or `__modules_a/z` symbols, otherwise you locate the RTR directory by hand from `InitializeModules`; x86-64 only; does not recover original method names (only virtual-slot names and renames you propagate).
- **ida-nativeaot (Dump-GUY)**: IDAPython port of Washi's analyzer. Finds the RTR directory by symbol or signature scan (works on stripped samples), rehydrates the `hydrated` segment for .NET 8+, pointer-scan fallback for .NET 7/10, names virtual methods `<Class>::Method_N`, recovers UTF-16 strings, arrays, boxed objects; browser UI. .NET 7-10. When: NativeAOT in IDA. S. Free. Requires IDA 9.2+ (PySide6), x86-64 only. Active (push 2026-06, 81 stars, listed in the Hex-Rays plugin repo).
- **ida-nativeaot (advancedmonitoring)**: separate IDA plugin. Locates RTR without a CLR header, rehydrates DEHYDRATED_DATA, recovers MethodTables and frozen strings/arrays, and auto-applies a FLIRT signature cache for .NET 7, 8, 9, 10 on windows-x64 and linux-x64 (PE and ELF). IDA 7.x-9.x. S. Free. **[UNVERIFIED]** maturity: 3 stars, last push 2026-05.
- **binja-nativeaot (YungBinary)**: Binary Ninja port of the IDA plugin; .NET 7-10+, static rehydration, pointer-scan fallback, browser UI. S. Free. Binary Ninja Plugin Manager. Small project (5 stars, push 2026-08).
- **Library-code signatures (FLIRT / WARP)**: more than 95 percent of a NativeAOT binary is framework code. Build a reference app with the same .NET version and runtime identifier, publish it AOT with its PDB, and generate signatures (IDA: idb2pat + FLAIR sigmake; Binary Ninja: WARP "From Current View"). Cyderes went from 34 of 4,588 functions named (under 1 percent) to 3,918 (over 85 percent) on a .NET 8 sample. HarfangLab published a .NET 7 FLIRT set only. When: always, right after identifying the exact .NET version string. S. Free (FLAIR needs an IDA license).
- **Runtime dump of the `hydrated` section**: Cyderes paused at `RehydrateData` and dumped the image. **D**, founder-gated. Sancho's static substitute is the plugin rehydration above.
- **Gaps**: no tool recovers original non-virtual method names or IL; reflection metadata is optional in NativeAOT and often trimmed. University of Twente with Hex-Rays has a funded project (Feb-Dec 2026) to restore type hierarchies and runtime semantics; no tool released yet. CrowdStrike talk at AVAR 2025 reports about 75 percent of .NET AOT samples seen in the wild were malicious.

Go:
- **GoReSym (Mandiant)**: recovers Go function names, types, build info and version from pclntab, including stripped binaries. When: DiE or strings show a Go build ID. S. Free. GitHub release binary. Active (2026-11).
- **Ghidra / IDA built-in Go support**: both now parse Go metadata natively (IDA 8.x+, Ghidra 10.3+). S.
- **GoStringUngarbler (Mandiant)**: undoes garble string obfuscation. S. **[ABANDONED]** (archived 2025-02); still usable on matching garble versions.

Rust:
- No dominant dedicated tool. Analysts use the Ghidra/IDA/Binary Ninja Rust demanglers, FLOSS Rust string support, and signatures built from the matching rustc and crate versions (version strings are in the binary). S. Free. **[UNVERIFIED]** that any single Rust-specific plugin is the current standard.

Delphi:
- **IDR (Interactive Delphi Reconstructor)**: Delphi/C++Builder class, form and RTTI recovery. When: DiE says Delphi. S. Free. Windows. **[STALE]** (last push 2023-08). Alternatives: Ghidra/IDA Delphi RTTI scripts (for example `Dhrake` style scripts).

AutoIt:
- **AutoIt-Ripper (nazywam)**: extracts the compiled AutoIt script from EXE overlays/resources. When: DiE says AutoIt. S. Free. `pip install autoit-ripper` (2026-03).

Python:
- **pyinstxtractor / pyinstxtractor-ng**: unpack PyInstaller archives to .pyc. When: DiE or strings show PyInstaller (`MEI`, `pyi`). S (the -ng fork never imports the payload). Free. `pip install pyinstxtractor-ng` (2026-07); original is a single script on GitHub (active 2026-07).
- **pycdc (Decompyle++)**: .pyc decompiler/disassembler covering modern Python versions, partial. When: after extraction. S. Free. Build from GitHub (CMake). Active (2026-04).
- **uncompyle6 / decompyle3**: decompilers for Python up to 3.8. S. Free. `pip install uncompyle6 decompyle3`. Limited for 3.9+.
- **PyLingual**: web decompiler for newer Python bytecode. S but uploads the bytecode. Free web service. **[UNVERIFIED]** retention terms.

Nim:
- **Nimfilt (ESET)**: IDA/Ghidra script that demangles Nim names and module paths. When: strings show `nim` runtime symbols. S. Free. GitHub. **[STALE]** (push 2024-10).

Electron / Node:
- **@electron/asar**: lists and extracts `app.asar` so the JS can be read. When: an Electron installer or `resources/app.asar`. S. Free. `npm install -g @electron/asar` then `asar extract app.asar out/`. Active.
- **Node SEA / pkg / nexe**: newer Node single-executable wrappers; extract the embedded blob with Binary Refinery or by carving. S. **[UNVERIFIED]** for a dedicated maintained extractor.

PowerShell:
- **PowerDecode**: layered PowerShell deobfuscator. S in its static mode; some layers invoke PowerShell to evaluate, which is execution. Free. GitHub. **[STALE]** (2024-04).
- **PSDecode**: PowerShell deobfuscator that overrides Invoke-Expression. **D** (runs the script under hooks). Free. **[ABANDONED]** (2021-02).
- **CyberChef / Binary Refinery**: the static path for Base64, gzip, XOR, char-code and string-reversal layers. S. Free.
- **PowerShell script block logs (Event ID 4104)**: the dynamic path in a sandbox. D.

JavaScript:
- **box-js**: JScript/JS sandbox that logs URLs, downloads and ActiveX calls. **D** (executes in an instrumented Node sandbox). Free. `npm install -g box-js`. Active (2026-07).
- **de4js**: web JS deobfuscator/unpacker. S. Free. **[ABANDONED]** (archived 2021).
- **Static JS path**: js-beautify/prettier, then CyberChef or Binary Refinery for decoding layers, then manual reading. Analysts also use `synchrony` and `webcrack` for obfuscator.io output (**[UNVERIFIED]** current maintenance).

VBA / Office:
- **oletools (olevba, oleid, rtfobj, mraptor, oleobj, msodde)**: extract and analyze VBA macros, OLE objects, RTF exploits, DDE. When: any Office, RTF, or OLE file. S. Free. `pip install oletools` (last release 2024-07, repo push 2026-02; treat as maintained but slow).
- **msoffcrypto-tool**: decrypt password-protected Office files (for example the "VelvetSweatshop" default). S. Free. `pip install msoffcrypto-tool` (2026-11).
- **ViperMonkey**: VBA emulator. **D** (emulation). Free. **[STALE]** (2024-07).
- **XLMMacroDeobfuscator**: Excel 4.0 macro emulator/deobfuscator. D (emulation). Free. **[UNVERIFIED]** status.
- **Didier Stevens Suite (oledump.py, zipdump.py, rtfdump.py, onedump.py, pdf-parser.py, pdfid.py)**: one-file Python triage tools for nearly every document format. S. Free. GitHub (active 2026-10).

PDF:
- **pdfid / pdf-parser (Didier Stevens)**: pdfid counts risky keywords (/JS, /OpenAction, /Launch, /EmbeddedFile); pdf-parser dumps and filters objects. When: any PDF. S. Free. Suite on GitHub; `pip install pdfid` exists but is older (2023).
- **peepdf**: interactive PDF analysis with JS extraction. Original **[ABANDONED]** (Python 2, 2024 push only). Use **peepdf-3**: `pip install peepdf-3` (6.0.3, 2026-10). S. Free.

LNK:
- **LnkParse3**: parses Windows shortcut files (target, arguments, machine ID, MAC, volume serial, timestamps). Machine ID and MAC are strong attribution pivots. S. Free. `pip install LnkParse3` (2026-02). Also `lnkinfo` from libyal (`brew install liblnk` **[UNVERIFIED]** formula name).

MSI:
- **msitools (msiinfo, msiextract)**: list tables and extract files and CustomAction scripts from MSI. S. Free. `brew install msitools`. Also Didier Stevens tools and `lessmsi` (Windows).

ISO / IMG / VHD:
- **7-Zip**: lists and extracts ISO, IMG, VHD contents without mounting (mounting on macOS can auto-open). S. Free. `brew install sevenzip` (or `p7zip`).

OneNote:
- **onedump.py (Didier Stevens)** / **one-extract**: extract embedded files (HTA, BAT, scripts) from .one files. S. Free. Suite on GitHub; `pip install one-extract` (2025-07). `pyonenote` is **[STALE]** (2023).

Android (adjacent):
- **jadx / apktool**: APK decompile and resource decode. S. Free. `brew install jadx apktool`.

## 4. Config extraction

- **CAPE-parsers / CAPEv2 extractors**: per-family config extractors used by CAPE (now split into the `CAPESandbox/CAPE-parsers` repo, active 2026-10). Many run statically on an unpacked payload; CAPE itself gets them unpacked dynamically. When: family identified and unpacked. S when run on a file you already have. Free. GitHub (pip install from repo).
- **MWCP (DC3)**: Malware Configuration Parser framework with a large parser set and a standard report schema. S. Free. `pip install mwcp` (3.16.1, 2026-05).
- **malduck (CERT Polska)**: helper library for writing extractors (crypto, compression, PE/ELF memory, YARA-driven "Extractor" modules); powers MWDB/Karton. S. Free. `pip install malduck` **[STALE]** (last release 2024-05, repo push 2025-06).
- **RATDecoders / malwareconfig (Kevin Breen)**: older RAT config decoders. **[ABANDONED]** in practice: PyPI `malwareconfig` last release 2020, repo push 2024. Still handy for legacy RATs.
- **MalConfScan (JPCERT)**: Volatility plugin that extracts configs from memory. Memory-dump only. **[STALE]** (2023).
- **CyberChef (GCHQ)**: browser "swiss army knife" for decoding (Base64, XOR, RC4, AES, gzip, regex extract). When: every manual decoding step; recipes are shareable as evidence. S. Free. Use the offline single-file build; do not paste case data into the public hosted instance if the case is sensitive.
- **Binary Refinery**: CLI equivalent of CyberChef for repeatable decode chains. S. Free. `pip install binary-refinery`.

## 5. Dynamic (sandbox only, founder-gated)

All of these execute or emulate the sample. Sancho does not run any of them without founder approval for the case. Public-by-default services also disclose the sample to the world, which can tip off the actor and destroys the client's control of the evidence.

Hosted sandboxes:
- **Triage (tria.ge, Recorded Future Sandbox, formerly Hatching)**: fast multi-OS sandbox with family tagging and config extraction. Free public tier: **submissions are public**. Paid private tiers. D.
- **ANY.RUN**: interactive sandbox. Free tier: **all tasks are public**. Paid plans add private tasks. D.
- **Hybrid Analysis (CrowdStrike Falcon Sandbox)**: free community sandbox. **Public by default** (reports and samples visible to the community). Paid Falcon Sandbox is private. D.
- **Joe Sandbox**: deep multi-OS sandbox. Joe Sandbox Cloud Basic (free) **publishes reports**; paid Cloud Pro / on-prem are private. D.
- **VMRay**: commercial hypervisor-based sandbox. Private. Paid. D.
- **UnpacMe**: see phase 2. Executes server side; check its sharing settings per tier (**[UNVERIFIED]** default visibility on the free tier).
- **Intezer Analyze**: genetic code-reuse analysis; free tier is 10 **public** file scans per month; Intezer has pivoted to "Autonomous SOC". Paid for private. Mostly static code-reuse plus dynamic in places. Disclosure decision.

Self-hosted (private, nothing leaves):
- **CAPEv2**: open-source sandbox (Cuckoo successor) with unpacking and config extraction. D. Free. Linux host. Very active (2026-11).
- **FLARE-VM (Mandiant)**: Windows analysis VM install script (dnSpyEx, x64dbg, IDA Free, PE-bear and more). D environment. Free. Active (2026-10).
- **REMnux**: Ubuntu-based Linux analysis distro/toolkit; also Docker images per tool. Mostly S tools, plus some D (emulators, network fakes). Free.
- **Procmon / Sysinternals**: process, file and registry activity capture. D. Free. Windows.
- **x64dbg**: Windows user-mode debugger. D. Free. Active.
- **Frida**: dynamic instrumentation/hooking. D. Free. `pip install frida-tools`.
- **Speakeasy (Mandiant)**: Windows user and kernel emulator for shellcode and PE. D (emulation). Free. Install from GitHub (repo active 2026-11; the PyPI package `speakeasy-emulator` is **[STALE]**, 2022).
- **Qiling**: cross-platform binary emulation framework. D (emulation). Free. `pip install qiling` (**[STALE]** PyPI release 2023; repo active 2026-10).
- **flare-emu**: IDA/radare2 emulation helper. D. **[ABANDONED]** (archived 2025-08).
- **FakeNet-NG (Mandiant)**: fakes network services so malware talks to the lab, not the internet. D-support. Free. Active (2026-10).
- **INetSim**: Linux fake internet services. D-support. Free. On REMnux. **[UNVERIFIED]** release cadence.
- **mitmproxy**: TLS-intercepting proxy for lab traffic. D-support. Free. `brew install --cask mitmproxy`.

Containment note for Sancho: with a sandbox, block real egress (FakeNet-NG/INetSim) so the run cannot touch attacker infrastructure, which his second limit forbids.

## 6. Intel and pivoting

- **VirusTotal**: AV verdicts, relations (contacted domains/IPs, parents, bundled files), retrohunt, VT Graph. When: first lookup by hash. S. Free (public API, low quota), paid Enterprise/GTI. Install: `pip install vt-py`. **Privacy**: a hash search sends only the hash. An upload makes the report public and VT says file contents "may be shared with premium VirusTotal customers", who can search and download them; actors monitor VT for their own hashes. Private Scanning (paid license) keeps files inside the org. Rule for Sancho: hash lookups yes, uploads only with founder approval.
- **MalwareBazaar (abuse.ch)**: free sample repository with tags, YARA hits, TLSH and imphash pivots. When: family pivoting, finding sibling samples. S lookup. Free (API key now required). Uploading makes a sample public.
- **URLhaus (abuse.ch)**: malware distribution URLs. S lookup. Free.
- **ThreatFox (abuse.ch)**: IOC database (C2s, hashes) tagged by family. S lookup. Free.
- **Malpedia (Fraunhofer FKIE)**: curated family encyclopedia with references and YARA rules, plus actor mapping. When: naming a family and finding prior reporting. S. Free (sample access needs vetting).
- **Hatching**: now Recorded Future Sandbox / tria.ge (see phase 5). Search public tria.ge reports by hash or family without submitting. S for searching.
- **UnpacMe**: also searchable by hash for already-unpacked children. S for search.
- **Intezer**: code-reuse genes against a family corpus. See phase 5 for disclosure.
- **MISP**: open-source threat-intel sharing platform. When: storing and sharing case IOCs with partners. Free. Self-hosted. Active.
- **OpenCTI (Filigran)**: STIX 2.1 knowledge graph for actors, campaigns, IOCs. Free (community) and paid. Self-hosted. Active.
- **crt.sh / Certificate Transparency**: certificates issued for a domain; finds sibling infrastructure. S (queries the CT log, not the attacker). Free.
- **Passive DNS (VT, Validin, SecurityTrails, DomainTools, Farsight/DNSDB)**: historical resolutions without touching the host. S. Mostly paid; VT and Validin have free tiers (**[UNVERIFIED]** current Validin free limits).
- **urlscan.io**: searching existing scans is S. **Submitting a scan makes urlscan fetch the URL**, which contacts attacker infrastructure (by urlscan, not you) and the scan can be public. For Sancho: search yes, submit only with founder approval, and use private visibility. Free and paid.
- **Shodan / Censys**: indexed banners, certificates, JARM/JA4 fingerprints; pivot on a known C2 to find siblings. S (you query their index, not the host). Free tiers, paid for full search.
- **Blockchain (EtherHiding, wallets)**:
  - **Etherscan / BscScan / Polygonscan**: contract source or bytecode, creation tx, deployer address, transaction and input-data history. S (public ledger via a third party). Free tier API.
  - **eth_call against a public RPC node (Infura, Alchemy, a public endpoint) or `cast call` from Foundry**: reads the stored payload from the contract, the same read-only call the malware makes (GTIG: EtherHiding retrieves with eth_call, no transaction, no gas). It contacts a blockchain node, not attacker-run infrastructure, but the returned data is attacker-controlled and can be updated at any time (GTIG: about 1.37 USD per update), so record block number and timestamp. Use an archive node to read historical state. S. Free. `brew install foundry` (**[UNVERIFIED]** formula; official install is `curl -L https://foundry.paradigm.xyz | bash`).
  - **Breadcrumbs**: wallet flow tracing and graphing. S. Free tier and paid.
  - **Arkham Intelligence**: entity-labelled blockchain explorer. S. Free tier and paid.

## 7. Detection outputs

- **YARA / YARA-X rules**: write string plus structural (pe module, imphash, section) conditions; test against goodware for false positives. Tools: **yarGen** (auto-generates candidate rules, needs goodware DB, `git clone Neo23x0/yarGen`, push 2026-01), YARA-X `yr check`/`yr scan`. Free.
- **Sigma**: generic SIEM detection rules for host/log behaviour. `pip install sigma-cli pysigma` (both 2026-11) to convert to Splunk, Elastic, Sentinel and others. SigmaHQ rule repo for reference. Free.
- **Suricata / Snort rules**: network signatures for C2 patterns, JA3/JA4, TLS SNI, HTTP URIs. `brew install suricata snort`; test against a pcap with `suricata -r file.pcap`. Free (plus paid ET Pro feeds).
- **STIX 2.1**: structured IOC and relationship export for MISP/OpenCTI. `pip install stix2` (2026-02). Free.
- **capa rules / Elastic protections-artifacts**: reference rule sets to compare against. Free.

## 8. Memory and network forensics (brief)

- **Volatility 3**: memory image analysis (processes, injected code with `malfind`, network, handles). S on the image. Free. `pip install volatility3` (2.28.2, 2026-09). Volatility 2 is **[ABANDONED]** (archived 2025-05).
- **Wireshark / tshark**: pcap analysis. S on the pcap. Free. `brew install wireshark` (CLI incl. tshark) or `brew install --cask wireshark` (GUI).
- **Zeek**: turns pcaps into protocol logs (conn, dns, http, ssl, x509, files). S on the pcap. Free. `brew install zeek`.
- **NetworkMiner**: extracts files, hosts, credentials from pcaps. S. Free and paid. Windows/Mono. **[UNVERIFIED]** macOS support.

## Published toolkits from senior analysts

- **Mandiant FLARE team**: FLARE-VM package list and the open-source repos capa, FLOSS, GoReSym, Speakeasy, FakeNet-NG, plus the FLARE-On challenge write-ups.
- **OALabs (Sergei Frankoff, Sean Wilson)**: UnpacMe, HashDB, the research blog and tool guides, YouTube tutorials.
- **SANS FOR610 (Lenny Zeltser, Anuj Soni)**: the course is built around REMnux plus a Windows VM; the REMnux "Discover the Tools" docs are the public mirror of that toolkit, organised by analysis task.
- **REMnux documentation**: per-category tool list (examine static properties, statically analyze code, dynamically reverse-engineer, analyze documents, memory, network).
- **hasherezade**: PE-bear, PE-sieve, HollowsHunter, mal_unpack, tutorials.
- **Didier Stevens**: the Didier Stevens Suite and blog, the standard for document triage.
- **Washi (Washi1337)**: AsmResolver, ghidra-nativeaot, the NativeAOT metadata blog post.

## Sources

NativeAOT:
- Washi, "Recovering Metadata from .NET Native AOT Binaries" (2025-04-18): https://blog.washi.dev/posts/recovering-nativeaot-metadata/
- ghidra-nativeaot: https://github.com/Washi1337/ghidra-nativeaot
- ida-nativeaot (Dump-GUY): https://github.com/dump-guy/ida-nativeaot
- ida-nativeaot (advancedmonitoring): https://github.com/advancedmonitoring/ida-nativeaot
- binja-nativeaot: https://github.com/YungBinary/binja-nativeaot
- Cyderes Howler Cell, "Reverse Engineering .NET AOT Malware" (2026-03-17): https://www.cyderes.com/howler-cell/reverse-engineering-net-aot-malware
- HarfangLab, "An introduction to reverse engineering .NET AOT applications" (2024-01-15): https://harfanglab.io/insidethelab/reverse-engineering-ida-pro-aot-net/
- University of Twente / Hex-Rays project: https://www.utwente.nl/en/eemcs/scs/research/running-projects/20260317-automated-analysis-and-reversing-of-net-malware/
- AVAR 2025, "Shadows in Native Code" (CrowdStrike): https://events.aavar.org/avar2025/?p=11677
- capa rule "compiled with .NET AoT": https://mandiant.github.io/capa/rules/compiled%20with%20.NET%20AoT
- Hex-Rays plugin repo: https://plugins.hex-rays.com/category/recently-added
- .NET reflection in AOT mode: https://github.com/dotnet/runtime/blob/v8.0.0/src/coreclr/nativeaot/docs/reflection-in-aot-mode.md

Tools and services:
- Detect It Easy: https://github.com/horsicq/Detect-It-Easy
- capa: https://github.com/mandiant/capa ; FLOSS: https://github.com/mandiant/flare-floss ; GoReSym: https://github.com/mandiant/GoReSym
- Speakeasy: https://github.com/mandiant/speakeasy ; FakeNet-NG: https://github.com/mandiant/flare-fakenet-ng ; FLARE-VM: https://github.com/mandiant/flare-vm
- YARA-X: https://github.com/VirusTotal/yara-x ; YARA: https://github.com/VirusTotal/yara
- dnSpyEx: https://github.com/dnSpyEx/dnSpy ; ILSpy: https://github.com/icsharpcode/ILSpy ; de4dot (archived): https://github.com/de4dot/de4dot ; NETReactorSlayer: https://github.com/SychicBoy/NETReactorSlayer
- pyinstxtractor-ng: https://github.com/pyinstxtractor/pyinstxtractor-ng ; pycdc: https://github.com/zrax/pycdc
- IDR: https://github.com/crypto2011/IDR ; AutoIt-Ripper: https://github.com/nazywam/AutoIt-Ripper ; Nimfilt: https://github.com/eset/nimfilt
- oletools: https://github.com/decalage2/oletools ; Didier Stevens Suite: https://github.com/DidierStevens/DidierStevensSuite ; peepdf-3: https://pypi.org/project/peepdf-3/
- box-js: https://github.com/CapacitorSet/box-js ; PowerDecode: https://github.com/Malandrone/PowerDecode ; PSDecode: https://github.com/R3MRUM/PSDecode
- CAPEv2: https://github.com/kevoreilly/CAPEv2 ; CAPE-parsers: https://github.com/CAPESandbox/CAPE-parsers ; MWCP: https://github.com/dod-cyber-crime-center/DC3-MWCP ; malduck: https://github.com/CERT-Polska/malduck ; RATDecoders: https://github.com/kevthehermit/RATDecoders
- Binary Refinery: https://github.com/binref/refinery ; CyberChef: https://github.com/gchq/CyberChef
- VirusTotal Private Scanning and sharing terms: https://docs.virustotal.com/docs/private-scanning ; https://docs.virustotal.com/docs
- Intezer free tier update: https://www.intezer.com/blog/intezer-analyze/an-important-update/
- GTIG EtherHiding (Oct 2025): https://cloud.google.com/blog/topics/threat-intelligence/dprk-adopts-etherhiding ; coverage: https://thehackernews.com/2025/10/north-korean-hackers-use-etherhiding-to.html
- REMnux docs and FOR610 link: https://docs.remnux.org/tips/malware-analysis-training ; https://docs.remnux.org/llms-full.txt ; https://sans.org/FOR610
- Volatility 3: https://github.com/volatilityfoundation/volatility3 ; Zeek: https://github.com/zeek/zeek ; Sigma: https://github.com/SigmaHQ/sigma ; pySigma: https://github.com/SigmaHQ/pySigma
- Status data: GitHub REST API `repos/{owner}/{repo}` and PyPI JSON API, queried 2026-11-15.
