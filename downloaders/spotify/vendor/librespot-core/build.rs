fn main() {
    // Emit placeholder build-info env vars (vergen skipped to avoid dep conflict)
    println!("cargo:rustc-env=VERGEN_BUILD_DATE=unknown");
    println!("cargo:rustc-env=VERGEN_GIT_SHA=unknown");
    println!("cargo:rustc-env=VERGEN_GIT_COMMIT_DATE=unknown");
    println!("cargo:rustc-env=LIBRESPOT_BUILD_ID=local");
}
