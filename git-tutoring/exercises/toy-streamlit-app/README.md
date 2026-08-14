# Toy Exercise: Streamlit App with Git

This exercise lets beginners practice Git with a tiny Streamlit app.

## Files

```text
app.py
requirements.txt
data/jobs.csv
```

## Run Locally

From this folder:

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Practice Workflow

1. Create a branch.

```bash
git switch -c update-toy-dashboard
```

2. Edit the app title in `app.py`.
3. Check status.

```bash
git status
```

4. Stage only the changed file.

```bash
git add git-tutoring/exercises/toy-streamlit-app/app.py
```

5. Commit.

```bash
git commit -m "Update toy dashboard title"
```

6. Push.

```bash
git push origin update-toy-dashboard
```

7. Open GitHub and compare the branch with `main`.

## Optional Practice: Create a Conflict

With a partner:

1. Both edit the same title line in `app.py` differently.
2. Both commit on separate branches.
3. Merge one branch first.
4. Try to merge the second branch.
5. Resolve the conflict manually.

This is a safe toy environment for learning what a conflict looks like.
