"""Synthetic recovery controls against verified offline release assets; never edits product.

Uses the shipped CLI and shared transaction engine. Fault injection changes
the host boundary, never upgrade semantics. Release process owns its use.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import time
from unittest import mock


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--product', required=True, type=Path)
    p.add_argument('--candidate-source', required=True, type=Path)
    p.add_argument('--candidate-lock', required=True, type=Path)
    p.add_argument('--candidate-sha256', required=True)
    p.add_argument('--candidate-commit', required=True)
    p.add_argument('--candidate-version', required=True)
    p.add_argument('--old-assets', required=True, type=Path,
                   help='JSON list of {version,source,lock,sha256} for every pinned published baseline')
    p.add_argument('--out', required=True, type=Path, help='New, nonexistent evidence directory')
    p.add_argument('--child', nargs=3, metavar=('TARGET', 'PROPOSAL', 'DIGEST'), help=argparse.SUPPRESS)
    return p


def snapshot(root):
    excluded = {'proposals', 'receipts', 'journals', 'staging'}
    result = {}
    for p in sorted(root.rglob('*')):
        rel = p.relative_to(root)
        if '.git' in rel.parts or '__pycache__' in rel.parts:
            continue
        if rel.parts[0] == '.context-os' and (len(rel.parts) > 1 and
                (rel.parts[1] in excluded or rel.parts[1] == 'apply.lock')):
            continue
        if p.is_file():
            result[rel.as_posix()] = {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                                     'mode': p.stat().st_mode & 0o7777}
    return result


def main():
    args = parser().parse_args()
    product = args.product.resolve()
    # The orchestration verifies this archive before starting this process.
    # Both parent and crash child execute its kernel, never checkout bytes.
    candidate_source = args.candidate_source.resolve()
    sys.path.insert(0, str(candidate_source))
    from contextos import kernel
    from contextos.cli import main as cli
    from contextos.bundle_schema import verify_bundle
    assert Path(kernel.__file__).resolve().is_relative_to(candidate_source)

    if args.child:
        target, proposal_path, digest = args.child
        target, proposal_path = Path(target).resolve(), Path(proposal_path)
        proposal = json.loads(proposal_path.read_text(encoding='utf-8'))
        destinations = {(target / c['path']).resolve() for c in proposal['changes']
                        if c.get('action', 'write') == 'write'}
        original = kernel._publish_exclusive
        count = 0
        def abrupt_exit(source, destination):
            nonlocal count
            result = original(source, destination)
            if destination.resolve() in destinations:
                count += 1
                if count == 2:
                    print(json.dumps({'ready': True, 'pid': os.getpid(), 'publications': count}), flush=True)
                    # Keep this exact apply process alive while the parent proves lock exclusion.
                    if sys.stdin.readline().strip() != 'exit-now':
                        os._exit(80)
                    os._exit(79)
            return result
        with mock.patch.object(kernel, '_publish_exclusive', side_effect=abrupt_exit):
            kernel.apply_proposal(target, proposal_path, digest, 'generic')
        raise AssertionError('Second-publication crash control did not fire')

    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=product, text=True).strip() == args.candidate_commit
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)  # Preserve all previous evidence, including failures.
    result = {'kind': 'synthetic agent test / host fault emulation; not independent signoff',
              'candidate_commit': args.candidate_commit, 'candidate_version': args.candidate_version,
              'candidate_sha256': args.candidate_sha256, 'trials': []}
    counter = 0
    mapping = {}
    def safe(value):
        text = str(value)
        for prefix, label in sorted(mapping.items(), key=lambda x: len(x[0]), reverse=True):
            text = text.replace(prefix, label)
            text = text.replace(json.dumps(prefix)[1:-1], label)
        return text
    def save(name, value):
        (out / name).write_text(safe(json.dumps(value, indent=2))+'\n', encoding='utf-8')
    def call(label, *argv, expected=0):
        nonlocal counter
        counter += 1
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = cli([str(a) for a in argv])
        save(f'{counter:03d}-{label}.json', {'arguments': list(map(str, argv)), 'exit': status,
                                          'stdout': output.getvalue(), 'stderr': errors.getvalue()})
        assert status == expected, (label, status, safe(errors.getvalue()))
        return json.loads(output.getvalue()) if output.getvalue().startswith('{') else errors.getvalue()
    def bundle(asset):
        return ['--lock', asset['lock'], '--source', asset['source'], '--expect-sha256', asset['sha256']]
    def apply(target, proposal, label='apply', expected=0):
        return call(label, 'bundle', 'apply', '--target', target,
                    '--proposal', target / proposal['proposal'], '--confirm', proposal['proposal_digest'], expected=expected)
    mapping[str(product)] = '<product>'
    mapping[str(out)] = '<evidence>'
    mapping[str(args.old_assets.resolve())] = '<published-assets-spec>'
    candidate = {'source': str(args.candidate_source.resolve()), 'lock': str(args.candidate_lock.resolve()),
                 'sha256': args.candidate_sha256, 'version': args.candidate_version}
    mapping[candidate['source']] = '<candidate-source>'
    mapping[candidate['lock']] = '<candidate-lock>'
    verified = verify_bundle(Path(candidate['lock']), Path(candidate['source']), expected_sha256=candidate['sha256'])
    assert verified.version == args.candidate_version
    assert verified.lock['bundle']['source_git_commit'] == args.candidate_commit
    olds = json.loads(args.old_assets.read_text(encoding='utf-8'))
    published = runpy.run_path(str(product / 'scripts/qualify-release-migration.py'))['PUBLISHED']
    assert {a['version'] for a in olds} == set(published)
    try:
        for old in olds:
            version = old['version']
            old['source'], old['lock'] = str(Path(old['source']).resolve()), str(Path(old['lock']).resolve())
            mapping[old['source']], mapping[old['lock']] = f'<published-{version}-source>', f'<published-{version}-lock>'
            baseline = verify_bundle(Path(old['lock']), Path(old['source']), expected_sha256=old['sha256'])
            assert baseline.version == version
            case = out / ('from-'+version)
            case.mkdir()
            target = case / 'workspace'
            target.mkdir()
            subprocess.run(['git', 'init', '--quiet', str(target)], check=True, capture_output=True)
            assert Path(subprocess.check_output(['git','rev-parse','--show-toplevel'], cwd=target, text=True).strip()).resolve() == target
            assert subprocess.run(['git','rev-parse','HEAD'], cwd=target, capture_output=True).returncode != 0
            initial = call('init-'+version, 'workspace', 'init', '--target', target, *bundle(old),
                           '--agents', 'claude,codex', '--profile', 'full-template')
            initial_receipt = apply(target, initial, 'init-apply-'+version)
            assert initial_receipt['git_head_before'] is None and initial_receipt['git_head_after'] is None
            local = target / 'projects/lantern/local.md'
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_text('Synthetic local Lantern context must survive.\n', encoding='utf-8')
            # Each case references its own verified copy; source drift cannot touch release assets.
            source = case / 'candidate-copy'
            shutil.copytree(Path(candidate['source']), source)
            own = dict(candidate, source=str(source))
            update = ['workspace', 'update', '--target', target, *bundle(own),
                      '--current-lock', old['lock'], '--current-source', old['source'],
                      '--expect-current-sha256', old['sha256'], '--agents', 'claude,codex', '--profile', 'full-template']
            p = call('update-'+version, *update)
            doc = json.loads((target / p['proposal']).read_text(encoding='utf-8'))
            writes = [c for c in doc['changes'] if c.get('action','write') == 'write']
            assert len(writes) >= 3, 'Candidate must exercise multiple real durable publications'
            before = snapshot(target)
            save('before-'+version+'.json', before)
            receipt_files = set((target/'.context-os/receipts').glob('*'))
            changed_source = source / next(r for r in verified.records if (source/r).is_file())
            original_source = changed_source.read_bytes()
            changed_source.write_bytes(original_source+b'\nsynthetic source drift\n')
            apply(target, p, 'source-drift-'+version, expected=2)
            assert snapshot(target) == before and set((target/'.context-os/receipts').glob('*')) == receipt_files
            changed_source.write_bytes(original_source)
            changed_target = target / next(c['path'] for c in writes if (target/c['path']).is_file())
            original_target = changed_target.read_bytes()
            changed_target.write_bytes(original_target+b'\nsynthetic target drift\n')
            drift_before = snapshot(target)
            apply(target, p, 'target-drift-'+version, expected=2)
            assert snapshot(target) == drift_before and set((target/'.context-os/receipts').glob('*')) == receipt_files
            changed_target.write_bytes(original_target)
            assert snapshot(target) == before
            destinations = {(target/c['path']).resolve() for c in writes}
            original_publish = kernel._publish_exclusive
            publications = []
            def fail_after_second(source_path, destination):
                published = original_publish(source_path, destination)
                if destination.resolve() in destinations:
                    publications.append(destination.relative_to(target).as_posix())
                    if len(publications) == 2:
                        raise OSError('synthetic exception after second durable publication')
                return published
            with mock.patch.object(kernel, '_publish_exclusive', side_effect=fail_after_second):
                failure = apply(target, p, 'exception-'+version, expected=2)
            assert len(publications) >= 2 and 'rolled back' in failure
            assert snapshot(target) == before and set((target/'.context-os/receipts').glob('*')) == receipt_files
            save('rollback-'+version+'.json', {'publications': publications, 'after': snapshot(target), 'exact': True})
            child_args = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--child',
                          str(target), str(target/p['proposal']), p['proposal_digest']]
            child = subprocess.Popen(child_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'})
            # A bounded reader prevents a missing injection from hanging qualification.
            import concurrent.futures
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            ready_future = pool.submit(child.stdout.readline)
            try:
                marker = json.loads(ready_future.result(timeout=60))
                assert marker == {'ready': True, 'pid': child.pid, 'publications': 2}
                assert child.poll() is None
                lock = target/'.context-os/apply.lock'
                assert lock.read_text().strip() == f'pid={child.pid}'
                journals = list((target/'.context-os/journals').iterdir())
                assert journals and snapshot(target) != before
                locked = apply(target, p, 'live-lock-'+version, expected=2)
                assert 'lock' in locked and child.poll() is None
                shutil.copytree(target/'.context-os/journals', case/'crash-journals')
                (case/'crash-lock.txt').write_bytes(lock.read_bytes())
                child.stdin.write('exit-now\n')
                child.stdin.flush()
                stdout, stderr = child.communicate(timeout=60)
                assert child.returncode == 79  # This exact child is now terminal and reaped.
                save('child-'+version+'.json', {'marker':marker, 'exit':child.returncode, 'stdout':stdout, 'stderr':stderr})
                assert lock.exists() and list((target/'.context-os/journals').iterdir())
                lock.unlink()  # Only after exact child exit; journal remains for shared-engine recovery.
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=10)
                pool.shutdown(wait=False)
            with mock.patch('contextos.cli.doctor', side_effect=kernel.ContextOSError('synthetic post-receipt doctor failure')):
                failure = apply(target, p, 'recovery-doctor-failure-'+version, expected=2)
            assert 'doctor failure' in failure and 'rolled back' not in failure
            receipts = [json.loads(r.read_text()) for r in (target/'.context-os/receipts').glob('*')
                        if r not in receipt_files]
            assert len(receipts) == 1 and receipts[0]['proposal_digest'] == p['proposal_digest']
            assert receipts[0]['git_head_before'] is None and receipts[0]['git_head_after'] is None
            assert json.loads((target/'.context-os/installed-bundle.json').read_text())['bundle']['sha256'] == candidate['sha256']
            assert json.loads((target/'contextos.workspace.json').read_text())['template']['bundle_sha256'] == candidate['sha256']
            assert local.read_text() == 'Synthetic local Lantern context must survive.\n'
            assert not list((target/'.context-os/journals').iterdir()) and not (target/'.context-os/apply.lock').exists()
            actual_doctor = call('doctor-'+version, '--root', target, 'doctor')
            save('committed-after-doctor-error-'+version+'.json', {'receipt':receipts[0], 'snapshot':snapshot(target), 'doctor':actual_doctor})
            result['trials'].append({'from':version, 'source_drift_rejected':True, 'target_drift_rejected':True,
                'second_publication_exception_exact_rollback':True, 'live_child_lock_exclusion':True,
                'exact_child_exit':79, 'same_proposal_recovered':True, 'post_receipt_doctor_error_committed':True,
                'proposal_digest':p['proposal_digest'], 'git_evidence':'independent unborn Git fixture; null HEAD'})
            save('results.json', result)
    except BaseException as exc:
        result['failure'] = safe(repr(exc))
        save('results.json', result)
        raise
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    if not __debug__:
        raise RuntimeError('Qualification requires assertions enabled')
    main()
