"""API serializers for auth, entitlements, usage, rewards, and webhooks."""
from rest_framework import serializers

from apps.plans.models import PlanType


# ── Auth ──


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, write_only=True)

    def validate_email(self, value):
        from apps.users.models import CustomUser

        if CustomUser.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value.lower()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class ResendVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()


class UserSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class ProfileSerializer(serializers.Serializer):
    plan_type = serializers.ChoiceField(choices=PlanType.choices, read_only=True)
    is_pro_active = serializers.BooleanField(read_only=True)
    display_name = serializers.CharField(read_only=True)


class MeSerializer(serializers.Serializer):
    user = UserSerializer(read_only=True)
    profile = ProfileSerializer(read_only=True)


# ── Usage ──


class UsageEventSerializer(serializers.Serializer):
    event_type = serializers.CharField(max_length=50)
    prompt_count = serializers.IntegerField(default=0, min_value=0)
    metadata = serializers.DictField(required=False, default=dict)


# ── Rewards ──


class GrantRewardSerializer(serializers.Serializer):
    user_email = serializers.EmailField()
    amount = serializers.IntegerField(min_value=1)
    source = serializers.CharField(max_length=50)
    reference_id = serializers.CharField(max_length=128, required=False, allow_blank=True)
    metadata = serializers.DictField(required=False, default=dict)

class ClaimReviewRewardSerializer(serializers.Serializer):
    reviewer_name = serializers.CharField(max_length=100)


# ── Extractions ──

from apps.extractions.models import SavedExtraction

class SavedExtractionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedExtraction
        fields = [
            "id",
            "video_name",
            "video_concept",
            "voiceover_text",
            "character_sheets",
            "shots",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
