# Migration to unmonitarr Organization - v0.9.0

This guide walks you through creating a fresh repository under the `unmonitarr` GitHub organization with clean commit history.

## Prerequisites

1. Create the new repository on GitHub:
   - Go to https://github.com/organizations/unmonitarr/repositories/new
   - Repository name: `unmonitarr`
   - Make it public
   - **Do NOT initialize** with README, .gitignore, or license (we're pushing existing code)

## Step 1: Remove Old Git History

```bash
cd /Users/charliecarpinteri/docker/unmonitarr

# Backup current state (optional but recommended)
cp -r .git .git.backup

# Remove existing git history
rm -rf .git
```

## Step 2: Initialize Fresh Repository

```bash
# Initialize new git repo
git init

# Create main branch
git checkout -b main
```

## Step 3: Stage All Files

```bash
# Add all files
git add .

# Verify what will be committed
git status
```

## Step 4: Create Initial Commit

```bash
# Create the initial commit
git commit -m "Initial release v0.9.0

Features:
- Time-delayed monitoring for Radarr and Sonarr
- Webhook support for instant updates on content addition
- Scheduled checks at configurable intervals
- Smart tagging system for tracking managed items
- Support for ignore tags to exclude items
- Dry-run mode for safe testing
- Docker and Docker Compose support
- Health check endpoint for monitoring
"
```

## Step 5: Tag the Release

```bash
# Create annotated tag for v0.9.0
git tag -a v0.9.0 -m "Release v0.9.0 - Initial public release

This is the first official release of unmonitarr.

Key features:
- Radarr and Sonarr integration
- Webhook triggers for instant processing
- Automated scheduled checks
- Smart time-delayed monitoring
- Comprehensive Docker support

See README.md for full documentation.
"
```

## Step 6: Add Remote and Push

```bash
# Add the new GitHub remote
git remote add origin https://github.com/unmonitarr/unmonitarr.git

# Verify remote
git remote -v

# Push main branch
git push -u origin main

# Push the tag (this triggers Docker image build)
git push origin v0.9.0
```

## Step 7: Verify GitHub Actions

After pushing:

1. Go to https://github.com/unmonitarr/unmonitarr/actions
2. You should see a workflow running for the tag push
3. It will build and publish:
   - `ghcr.io/unmonitarr/unmonitarr:latest`
   - `ghcr.io/unmonitarr/unmonitarr:v0.9.0`
   - `ghcr.io/unmonitarr/unmonitarr:0.9.0` (without 'v' prefix)

## Step 8: Test the Docker Image

Once the GitHub Action completes:

```bash
# Pull the new image
docker pull ghcr.io/unmonitarr/unmonitarr:v0.9.0

# Or pull latest
docker pull ghcr.io/unmonitarr/unmonitarr:latest

# Test it
docker run --rm \
  -p 5099:5099 \
  -e DRY_RUN=1 \
  -e ENABLE_RADARR=1 \
  -e RADARR_URL=http://your-radarr:7878 \
  -e RADARR_API_KEY=your_key \
  ghcr.io/unmonitarr/unmonitarr:v0.9.0
```

## Step 9: Update Your Local Deployment

Update your docker-compose.yml to use the new image:

```yaml
services:
  unmonitarr:
    image: ghcr.io/unmonitarr/unmonitarr:latest  # or :v0.9.0 for specific version
    # ... rest of config
```

Then:

```bash
docker-compose pull
docker-compose up -d
```

## Verification Checklist

- [ ] New repo created at https://github.com/unmonitarr/unmonitarr
- [ ] Clean commit history (only one commit)
- [ ] Tag v0.9.0 present
- [ ] GitHub Actions workflow completed successfully
- [ ] Docker images published to GHCR
- [ ] README badges show correct org (unmonitarr)
- [ ] Docker image pulls and runs successfully
- [ ] Webhooks work (test with curl)

## Rollback (If Needed)

If something goes wrong:

```bash
# Restore old git history
rm -rf .git
mv .git.backup .git

# You're back to the original state
```

## Future Releases

For future releases, follow semantic versioning:

```bash
# Make your changes
git add .
git commit -m "Your commit message"

# Tag new version
git tag -a v0.9.1 -m "Bug fixes and improvements"

# Push
git push origin main
git push origin v0.9.1
```

The GitHub Action will automatically build and publish the new version.

---

## Troubleshooting

### GitHub Actions fails with "unauthorized"

Make sure the repository has the correct permissions:
- Settings → Actions → General
- Workflow permissions: "Read and write permissions"

### Docker image not found

- Check GHCR package visibility (should be public)
- Go to: https://github.com/orgs/unmonitarr/packages
- Click on the package → Package settings → Change visibility to Public

### Badge images not showing

Badges need time to generate. If they show 404:
- Wait a few minutes after first release
- Ensure repository and packages are public
