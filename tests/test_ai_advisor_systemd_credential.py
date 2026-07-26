import os
import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.ai_advisor.credential_loader import CredentialResolutionStatus
from backend.ai_advisor.isolated_smoke_runner import (
    IsolatedSmokeTestRunner,
    SmokeTestMode,
    isolated_non_secret_environment,
)
from backend.ai_advisor.production_config_loader import (
    EnvironmentProductionConfigLoader,
    InjectedProductionConfigLoader,
)
from backend.ai_advisor.provider_config import (
    CredentialReference,
    CredentialSource,
    ProviderName,
)
from backend.ai_advisor.credential_loader import CredentialResolutionInput
from backend.ai_advisor.systemd_credential_loader import (
    MAX_SYSTEMD_CREDENTIAL_BYTES,
    SystemdCredentialAvailability,
    SystemdCredentialLoader,
)
from tests.test_ai_advisor_isolated_smoke_runner import (
    NOW,
    approval,
    response_text,
)
from tests.test_ai_advisor_openai_sdk_transport import (
    FakeClient,
    FakeClientFactory,
    FakeResponse,
    FakeResponses,
)


def resolution_input(name, source=CredentialSource.SYSTEMD_CREDENTIAL):
    return CredentialResolutionInput(
        credentialReference=CredentialReference(
            credentialId=name,
            source=source,
        ),
        provider=ProviderName.OPENAI,
        allowEnvironmentRead=False,
    )


class CountingLoader:
    def __init__(self, delegate):
        self.delegate = delegate
        self.calls = 0

    def resolve(self, value):
        self.calls += 1
        return self.delegate.resolve(value)

    def probe(self, value):
        return self.delegate.probe(value)


class RemoveBeforeSecondResolution(CountingLoader):
    def __init__(self, delegate, path):
        super().__init__(delegate)
        self.path = path

    def resolve(self, value):
        self.calls += 1
        if self.calls == 2:
            self.path.unlink()
        return self.delegate.resolve(value)


class SystemdCredentialLoaderTest(unittest.TestCase):
    def loader(self, directory, names=("AI_ADVISOR_AUTH_TOKEN",)):
        return SystemdCredentialLoader(
            names,
            credentialsDirectoryReader=lambda: directory,
        )

    def test_probe_and_loader_accept_allowlisted_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "AI_ADVISOR_AUTH_TOKEN")
            path.write_text("fake-auth-value", encoding="utf-8")
            loader = self.loader(directory)
            probe = loader.probe(resolution_input(path.name))
            result = loader.resolve(resolution_input(path.name))
            self.assertEqual(
                probe.availability,
                SystemdCredentialAvailability.AVAILABLE,
            )
            self.assertEqual(result.status, CredentialResolutionStatus.SUCCEEDED)
            self.assertNotIn("fake-auth-value", repr(loader) + repr(result))

    def test_reference_validation_rejects_unknown_and_unsafe_names(self):
        loader = self.loader("/nonexistent")
        names = (
            "UNKNOWN",
            "/absolute",
            ".",
            "..",
            "../traversal",
            "path/separator",
            "path\\separator",
            "nul\x00value",
        )
        for name in names:
            with self.subTest(name=repr(name)):
                result = loader.probe(resolution_input(name))
                self.assertEqual(
                    result.availability,
                    SystemdCredentialAvailability.REFERENCE_NOT_ALLOWED,
                )

    def test_probe_rejects_missing_symlink_directory_fifo_size_and_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            loader = self.loader(
                directory,
                (
                    "missing",
                    "link",
                    "directory",
                    "fifo",
                    "empty",
                    "oversize",
                    "denied",
                ),
            )
            Path(directory, "target").write_text("fake", encoding="utf-8")
            Path(directory, "link").symlink_to("target")
            Path(directory, "directory").mkdir()
            os.mkfifo(Path(directory, "fifo"))
            Path(directory, "empty").touch()
            Path(directory, "oversize").write_bytes(
                b"x" * (MAX_SYSTEMD_CREDENTIAL_BYTES + 1)
            )
            denied = Path(directory, "denied")
            denied.write_text("fake", encoding="utf-8")
            denied.chmod(0)
            expected = {
                "missing": SystemdCredentialAvailability.NOT_FOUND,
                "link": SystemdCredentialAvailability.SYMLINK_REJECTED,
                "directory": SystemdCredentialAvailability.NOT_REGULAR,
                "fifo": SystemdCredentialAvailability.NOT_REGULAR,
                "empty": SystemdCredentialAvailability.SIZE_INVALID,
                "oversize": SystemdCredentialAvailability.SIZE_INVALID,
                "denied": SystemdCredentialAvailability.PERMISSION_DENIED,
            }
            try:
                for name, availability in expected.items():
                    with self.subTest(name=name):
                        self.assertEqual(
                            loader.probe(resolution_input(name)).availability,
                            availability,
                        )
            finally:
                denied.chmod(0o600)

    def test_directory_unavailable_and_probe_reads_no_content(self):
        missing = SystemdCredentialLoader(
            ("AI_ADVISOR_AUTH_TOKEN",),
            credentialsDirectoryReader=lambda: None,
        )
        self.assertEqual(
            missing.probe(resolution_input("AI_ADVISOR_AUTH_TOKEN")).availability,
            SystemdCredentialAvailability.DIRECTORY_UNAVAILABLE,
        )
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "AI_ADVISOR_AUTH_TOKEN").write_text(
                "fake-auth-value",
                encoding="utf-8",
            )
            loader = self.loader(directory)
            with patch.object(os, "read", side_effect=AssertionError):
                self.assertEqual(
                    loader.probe(
                        resolution_input("AI_ADVISOR_AUTH_TOKEN")
                    ).availability,
                    SystemdCredentialAvailability.AVAILABLE,
                )

    def test_loader_rejects_invalid_content_without_normalization(self):
        invalid = (
            b"",
            b"x" * (MAX_SYSTEMD_CREDENTIAL_BYTES + 1),
            b"\xff",
            b" leading",
            b"trailing ",
            b"line\n",
            b"control\x01value",
            b"delete\x7fvalue",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "OPENAI_API_KEY")
            loader = self.loader(directory, ("OPENAI_API_KEY",))
            for payload in invalid:
                with self.subTest(payload=repr(payload[:20])):
                    path.write_bytes(payload)
                    result = loader.resolve(resolution_input(path.name))
                    self.assertEqual(result.status, CredentialResolutionStatus.FAILED)

    def test_no_cache_and_rotation_are_observed_per_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "OPENAI_API_KEY")
            loader = self.loader(directory, ("OPENAI_API_KEY",))
            path.write_text("fake-value-one", encoding="utf-8")
            first = loader.resolve(resolution_input(path.name))
            path.write_text("fake-value-two", encoding="utf-8")
            second = loader.resolve(resolution_input(path.name))
            self.assertEqual(first.credential._consume(), "fake-value-one")
            self.assertEqual(second.credential._consume(), "fake-value-two")

    def test_wrong_source_is_rejected_and_environment_loader_remains_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            loader = self.loader(directory)
            result = loader.resolve(
                resolution_input(
                    "AI_ADVISOR_AUTH_TOKEN",
                    source=CredentialSource.ENVIRONMENT,
                )
            )
            self.assertEqual(result.status, CredentialResolutionStatus.FAILED)
        loaded = InjectedProductionConfigLoader(
            {
                "authenticationCredentialId": "auth",
                "credentialId": "provider",
            }
        ).load()
        self.assertTrue(loaded.succeeded)
        self.assertEqual(
            loaded.configuration.authenticationCredentialReference.source,
            CredentialSource.INJECTED,
        )
        self.assertEqual(
            loaded.configuration.credentialReference.source,
            CredentialSource.INJECTED,
        )

    def test_production_config_selects_systemd_source_and_rejects_unknown(self):
        mapping = isolated_non_secret_environment()
        loaded = EnvironmentProductionConfigLoader(environmentReader=mapping.get).load()
        self.assertTrue(loaded.succeeded)
        self.assertEqual(
            loaded.configuration.authenticationCredentialReference.source,
            CredentialSource.SYSTEMD_CREDENTIAL,
        )
        self.assertEqual(
            loaded.configuration.credentialReference.source,
            CredentialSource.SYSTEMD_CREDENTIAL,
        )
        invalid = dict(mapping)
        invalid["AI_ADVISOR_CREDENTIAL_SOURCE"] = "AUTO"
        rejected = EnvironmentProductionConfigLoader(
            environmentReader=invalid.get
        ).load()
        self.assertFalse(rejected.succeeded)

    def test_systemd_authentication_failure_never_resolves_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            auth_path = Path(directory, "AI_ADVISOR_AUTH_TOKEN")
            auth_path.write_text("fake-auth-value", encoding="utf-8")
            Path(directory, "OPENAI_API_KEY").write_text(
                "fake-provider-value",
                encoding="utf-8",
            )
            auth = RemoveBeforeSecondResolution(
                SystemdCredentialLoader(
                    ("AI_ADVISOR_AUTH_TOKEN",),
                    credentialsDirectoryReader=lambda: directory,
                ),
                auth_path,
            )
            provider = CountingLoader(
                SystemdCredentialLoader(
                    ("OPENAI_API_KEY",),
                    credentialsDirectoryReader=lambda: directory,
                )
            )
            responses = FakeResponses(
                response=FakeResponse(
                    response_text(),
                    usage=SimpleNamespace(
                        input_tokens=1,
                        output_tokens=1,
                        total_tokens=2,
                    ),
                )
            )
            runner = IsolatedSmokeTestRunner(
                configLoader=EnvironmentProductionConfigLoader(
                    environmentReader=isolated_non_secret_environment().get
                ),
                authenticationCredentialLoader=auth,
                providerCredentialLoader=provider,
                allowedAuthenticationCredentialIds=("AI_ADVISOR_AUTH_TOKEN",),
                allowedProviderCredentialIds=("OPENAI_API_KEY",),
                approvedModels=("gpt-4o-mini",),
                clientFactory=FakeClientFactory(FakeClient(responses)),
            )
            result = runner.run(
                mode=SmokeTestMode.LIVE_ONE_SHOT,
                generated_at=NOW,
                live_approval=approval(),
            )
            self.assertFalse(result.invocationSucceeded)
            self.assertEqual(auth.calls, 2)
            self.assertEqual(provider.calls, 0)
            self.assertEqual(len(responses.calls), 0)

    def test_fake_systemd_credentials_complete_one_shot_e2e(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "AI_ADVISOR_AUTH_TOKEN").write_text(
                "fake-auth-value",
                encoding="utf-8",
            )
            Path(directory, "OPENAI_API_KEY").write_text(
                "fake-provider-value",
                encoding="utf-8",
            )
            auth = CountingLoader(
                SystemdCredentialLoader(
                    ("AI_ADVISOR_AUTH_TOKEN",),
                    credentialsDirectoryReader=lambda: directory,
                )
            )
            provider = CountingLoader(
                SystemdCredentialLoader(
                    ("OPENAI_API_KEY",),
                    credentialsDirectoryReader=lambda: directory,
                )
            )
            usage = SimpleNamespace(
                input_tokens=10,
                output_tokens=8,
                total_tokens=18,
            )
            responses = FakeResponses(
                response=FakeResponse(response_text(), usage=usage)
            )
            factory = FakeClientFactory(FakeClient(responses))
            mapping = isolated_non_secret_environment()
            runner = IsolatedSmokeTestRunner(
                configLoader=EnvironmentProductionConfigLoader(
                    environmentReader=mapping.get
                ),
                authenticationCredentialLoader=auth,
                providerCredentialLoader=provider,
                allowedAuthenticationCredentialIds=("AI_ADVISOR_AUTH_TOKEN",),
                allowedProviderCredentialIds=("OPENAI_API_KEY",),
                approvedModels=("gpt-4o-mini",),
                clientFactory=factory,
            )
            real_socket = socket.socket

            def no_network_socket(family=socket.AF_INET, *args, **kwargs):
                if family in {socket.AF_INET, socket.AF_INET6}:
                    raise AssertionError("network socket prohibited")
                return real_socket(family, *args, **kwargs)

            with (
                patch.object(socket, "socket", side_effect=no_network_socket),
                patch.object(socket, "create_connection", side_effect=AssertionError),
                patch.object(socket, "getaddrinfo", side_effect=AssertionError),
            ):
                first = runner.run(
                    mode=SmokeTestMode.LIVE_ONE_SHOT,
                    generated_at=NOW,
                    live_approval=approval(),
                )
                second = runner.run(
                    mode=SmokeTestMode.LIVE_ONE_SHOT,
                    generated_at=NOW,
                    live_approval=approval(),
                )
            self.assertTrue(first.invocationSucceeded)
            self.assertFalse(second.invocationSucceeded)
            self.assertIsNotNone(first.usage)
            self.assertEqual(auth.calls, 4)
            self.assertEqual(provider.calls, 1)
            self.assertEqual(factory.calls, 1)
            self.assertEqual(len(responses.calls), 1)


if __name__ == "__main__":
    unittest.main()
