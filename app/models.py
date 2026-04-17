from django.db import models
from django.utils import timezone


class TimeStemp(models.Model):
    """Abstract base model for created/updated timestamps."""
    created = models.DateTimeField(auto_now_add=True, verbose_name='Created')
    updated = models.DateTimeField(auto_now=True, verbose_name='Last Updated')

    class Meta:
        abstract = True


class Text(TimeStemp):
    """Source text record — used as a FK anchor for paraphrased/generated content."""
    PROCESS = (
        ('RUNNING', 'RUNNING'),
        ('NOT_DONE', 'NOT_DONE'),
        ('DONE', 'DONE'),
    )
    text = models.TextField()
    pharaphreased = models.CharField(choices=PROCESS, default='NOT_DONE', max_length=10)

    def __str__(self):
        return self.text[:80]


class ParaphrasedText(TimeStemp):
    """Stores ChatGPT-generated text along with its MongoDB reference."""
    sentence = models.ForeignKey(Text, on_delete=models.CASCADE)
    response = models.TextField()
    PageTitle = models.TextField()
    number = models.IntegerField(default=1)
    # ObjectId of the corresponding MongoDB document
    mongo_id = models.CharField(max_length=50, blank=True, default='')

    def __str__(self):
        return f"[{self.mongo_id}] {self.response[:60]}"


class user_details(TimeStemp):
    """ChatGPT account credentials + Selenium profile info + scheduling metadata."""
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)
    # Selenium Chrome profile directory name (e.g. "Profile 1")
    profile = models.CharField(max_length=255)
    # Root folder that holds all Chrome profiles (e.g. "Profiles")
    ProfileDict = models.CharField(max_length=255, default='Profiles')

    # --- Anti-bot scheduling fields ---
    # When was this account last handed a prompt task
    last_used_at = models.DateTimeField(null=True, blank=True)
    # When was the current continuous session started (resets after rest)
    session_started_at = models.DateTimeField(null=True, blank=True)
    # Account is locked from use until this timestamp
    rest_until = models.DateTimeField(null=True, blank=True)

    def is_resting(self):
        """Return True if this account is still in its mandated rest window."""
        if self.rest_until and self.rest_until > timezone.now():
            return True
        return False

    def __str__(self):
        return self.email