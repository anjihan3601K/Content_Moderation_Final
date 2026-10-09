import React, { useEffect, useState } from 'react';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Typography,
} from '@mui/material';
import {
  Person as PersonIcon,
  Save as SaveIcon,
} from '@mui/icons-material';
import { useAuthStore } from '../../store/authStore';
import { recommendationAPI } from '../../services/api';

const TIER_LABELS = {
  child: 'Child (under 13)',
  teen: 'Teen (13 to 17)',
  adult: 'Adult (18 and over)',
};

const TRUST_LABELS = {
  self_declared: 'Self-declared',
  parent_linked: 'Confirmed by a parent',
  verified: 'Verified',
};

const STRICTNESS_LABELS = { low: 'Low', medium: 'Medium', strict: 'Strict' };
const RATING_LABELS = { all_ages: 'All ages', teen: 'Teen', adult: 'Adult' };
const SENSITIVE_TOPICS = ['mental_health', 'dating_advice', 'politics_intro'];
const TIER_RANK = { child: 1, teen: 2, adult: 3 };

const formatTopic = (topic) => topic.replace(/_/g, ' ');

// Age in whole years on today's date, or null for a missing, future or implausible date.
const ageFromDateOfBirth = (dateOfBirth) => {
  if (!dateOfBirth) return null;
  const born = new Date(`${dateOfBirth}T00:00:00`);
  const today = new Date();
  if (Number.isNaN(born.getTime()) || born > today) return null;
  let age = today.getFullYear() - born.getFullYear();
  const hadBirthday =
    today.getMonth() > born.getMonth() ||
    (today.getMonth() === born.getMonth() && today.getDate() >= born.getDate());
  if (!hadBirthday) age -= 1;
  return age > 120 ? null : age;
};

const tierFromAge = (age) => {
  if (age === null) return null;
  if (age < 13) return 'child';
  if (age < 18) return 'teen';
  return 'adult';
};

const errorMessage = (err, fallback) => {
  const detail = err.response?.data?.detail;
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (detail.rejected) {
    return `These interests are not available for this age group: ${detail.rejected.map(formatTopic).join(', ')}`;
  }
  return fallback;
};

/**
 * Viewer profile card: age group, interests and parental controls.
 *
 * Without props it edits the logged-in user's own profile. An admin can pass `profileId`
 * and `adminMode` to manage another user's age group, age confirmation and parental controls.
 * `onSaved` is called after every successful save.
 */
const ViewerProfile = ({ profileId = null, adminMode = false, onSaved = null }) => {
  const { user } = useAuthStore();
  const targetId = profileId ?? user?.user_id;
  const [profile, setProfile] = useState(null);
  const [unavailable, setUnavailable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dateOfBirth, setDateOfBirth] = useState('');
  const [interests, setInterests] = useState([]);
  const [adminDraft, setAdminDraft] = useState(null);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  const applyProfile = (data) => {
    setProfile(data);
    setInterests(data.explicit_interests || []);
    setAdminDraft({
      age_tier: data.age_tier,
      age_trust_level: data.age_trust_level,
      strictness_level: data.parental_controls?.strictness_level || 'low',
      max_rating: data.parental_controls?.max_rating || '',
      blocked_categories: data.parental_controls?.blocked_categories || [],
      allowed_sensitive_topics: data.parental_controls?.allowed_sensitive_topics || [],
    });
  };

  useEffect(() => {
    const loadProfile = async () => {
      if (!targetId) return;
      setLoading(true);
      try {
        applyProfile(await recommendationAPI.getPreferences(targetId));
      } catch (err) {
        console.error('Error loading viewer profile:', err);
        if (err.response?.status === 404) {
          setUnavailable(true);
        } else {
          setError(errorMessage(err, 'Failed to load the profile'));
        }
      } finally {
        setLoading(false);
      }
    };
    loadProfile();
  }, [targetId]);

  const age = ageFromDateOfBirth(dateOfBirth);
  const derivedTier = tierFromAge(age);
  const raisesTier = profile && derivedTier && TIER_RANK[derivedTier] > TIER_RANK[profile.age_tier];

  const save = async (changes, message) => {
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const updated = await recommendationAPI.updatePreferences(targetId, changes);
      applyProfile(updated);
      setSuccess(message);
      if (onSaved) onSaved(updated);
      return true;
    } catch (err) {
      console.error('Error saving viewer profile:', err);
      setError(errorMessage(err, 'Failed to save the profile'));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const handleSaveAge = async () => {
    if (!derivedTier) {
      setError('Enter a valid date of birth');
      return;
    }
    if (await save({ age_tier: derivedTier }, 'Age group saved')) setDateOfBirth('');
  };

  const handleSaveInterests = () => save({ explicit_interests: interests }, 'Interests saved');

  const handleSaveAdmin = () =>
    save(
      {
        age_tier: adminDraft.age_tier,
        age_trust_level: adminDraft.age_trust_level,
        parental_controls: {
          strictness_level: adminDraft.strictness_level,
          max_rating: adminDraft.max_rating || null,
          blocked_categories: adminDraft.blocked_categories,
          allowed_sensitive_topics: adminDraft.allowed_sensitive_topics,
        },
      },
      'Age group and parental controls saved'
    );

  const setDraft = (field, value) => setAdminDraft({ ...adminDraft, [field]: value });

  if (loading) {
    return (
      <Card elevation={2}>
        <CardContent sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </CardContent>
      </Card>
    );
  }

  if (unavailable) {
    return (
      <Card elevation={2}>
        <CardContent>
          <Typography variant="h6" fontWeight="bold" gutterBottom>
            Viewer Profile
          </Typography>
          <Alert severity="info">
            Personalized recommendations are not enabled on this server.
          </Alert>
        </CardContent>
      </Card>
    );
  }

  const controls = profile?.parental_controls;
  const blockedCategories = controls?.blocked_categories || [];
  const learnedTopics = Object.entries(profile?.learned_interests || {}).sort((a, b) => b[1] - a[1]);

  return (
    <Card elevation={2}>
      <CardContent>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
          <PersonIcon color="primary" />
          <Typography variant="h6" fontWeight="bold">
            Viewer Profile
          </Typography>
        </Box>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          {adminMode
            ? 'Age group, age confirmation and parental controls for this user'
            : 'Your age group and interests decide what the recommendation feed shows you'}
        </Typography>

        <Divider sx={{ mb: 3 }} />

        {error && (
          <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 3 }}>
            {error}
          </Alert>
        )}

        {success && (
          <Alert severity="success" onClose={() => setSuccess(null)} sx={{ mb: 3 }}>
            {success}
          </Alert>
        )}

        {profile && (
          <>
            <Grid container spacing={2} sx={{ mb: 3 }}>
              <Grid item xs={12} sm={6}>
                <Typography variant="body2" color="text.secondary">
                  Age group
                </Typography>
                <Typography variant="body1" fontWeight="medium">
                  {TIER_LABELS[profile.age_tier]}
                  {!profile.tier_declared && ' (not yet declared)'}
                </Typography>
              </Grid>
              <Grid item xs={12} sm={6}>
                <Typography variant="body2" color="text.secondary">
                  Age confirmation
                </Typography>
                <Typography variant="body1" fontWeight="medium">
                  {TRUST_LABELS[profile.age_trust_level]}
                </Typography>
              </Grid>
            </Grid>

            {/* Date of birth (own profile only) */}
            {!adminMode && (
              <>
                <Typography variant="subtitle2" fontWeight="bold" gutterBottom>
                  Date of birth
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  Used once to work out your age group. Only the age group is saved; your date of birth is not stored.
                </Typography>
                <Grid container spacing={2} alignItems="center" sx={{ mb: 1 }}>
                  <Grid item xs={12} sm={5}>
                    <TextField
                      fullWidth
                      label="Date of Birth"
                      type="date"
                      value={dateOfBirth}
                      onChange={(e) => {
                        setDateOfBirth(e.target.value);
                        setError(null);
                      }}
                      InputLabelProps={{ shrink: true }}
                      inputProps={{ max: new Date().toISOString().slice(0, 10) }}
                    />
                  </Grid>
                  <Grid item xs={12} sm={4}>
                    <Typography variant="body2" color="text.secondary">
                      Age
                    </Typography>
                    <Typography variant="body1" fontWeight="medium">
                      {age === null ? 'Not entered' : `${age} years, ${TIER_LABELS[derivedTier]}`}
                    </Typography>
                  </Grid>
                  <Grid item xs={12} sm={3}>
                    <Button
                      fullWidth
                      variant="contained"
                      disabled={saving || !derivedTier || (derivedTier === profile.age_tier && profile.tier_declared)}
                      startIcon={<SaveIcon />}
                      onClick={handleSaveAge}
                    >
                      Save Age
                    </Button>
                  </Grid>
                </Grid>
                {raisesTier && (
                  <Alert severity="warning" sx={{ mb: 2 }}>
                    Moving to an older age group needs an administrator.
                  </Alert>
                )}

                <Divider sx={{ my: 3 }} />
              </>
            )}

            {/* Interests */}
            <Typography variant="subtitle2" fontWeight="bold" gutterBottom>
              Interests
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              {profile.allowed_topics
                ? 'Choose from the topics available for this age group'
                : 'Choose topics or type your own and press Enter'}
            </Typography>
            <Autocomplete
              multiple
              freeSolo={!profile.allowed_topics}
              options={profile.allowed_topics || []}
              value={interests}
              onChange={(event, value) => setInterests(value.map((topic) => topic.trim()).filter(Boolean))}
              getOptionLabel={formatTopic}
              renderTags={(value, getTagProps) =>
                value.map((topic, index) => (
                  <Chip label={formatTopic(topic)} size="small" {...getTagProps({ index })} key={topic} />
                ))
              }
              renderInput={(params) => <TextField {...params} label="Interests" placeholder="Add a topic" />}
            />
            <Button
              variant="contained"
              disabled={saving}
              startIcon={saving ? <CircularProgress size={20} /> : <SaveIcon />}
              onClick={handleSaveInterests}
              sx={{ mt: 2 }}
            >
              {saving ? 'Saving...' : 'Save Interests'}
            </Button>

            {learnedTopics.length > 0 && (
              <Box sx={{ mt: 3 }}>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  Learned from viewing
                </Typography>
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                  {learnedTopics.map(([topic, weight]) => (
                    <Chip
                      key={topic}
                      label={`${formatTopic(topic)} ${Math.round(weight * 100)}%`}
                      size="small"
                      variant="outlined"
                    />
                  ))}
                </Box>
              </Box>
            )}

            <Divider sx={{ my: 3 }} />

            {/* Parental controls */}
            <Typography variant="subtitle2" fontWeight="bold" gutterBottom>
              {adminMode ? 'Age group and parental controls' : 'Parental controls'}
            </Typography>

            {adminMode && adminDraft ? (
              <>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  Set on a parent's request. These settings override the user's interests.
                </Typography>
                <Grid container spacing={2}>
                  <Grid item xs={12} sm={6}>
                    <FormControl fullWidth>
                      <InputLabel>Age Group</InputLabel>
                      <Select label="Age Group" value={adminDraft.age_tier} onChange={(e) => setDraft('age_tier', e.target.value)}>
                        {Object.entries(TIER_LABELS).map(([value, label]) => (
                          <MenuItem key={value} value={value}>{label}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={12} sm={6}>
                    <FormControl fullWidth>
                      <InputLabel>Age Confirmation</InputLabel>
                      <Select
                        label="Age Confirmation"
                        value={adminDraft.age_trust_level}
                        onChange={(e) => setDraft('age_trust_level', e.target.value)}
                      >
                        {Object.entries(TRUST_LABELS).map(([value, label]) => (
                          <MenuItem key={value} value={value}>{label}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={12} sm={6}>
                    <FormControl fullWidth>
                      <InputLabel>Strictness</InputLabel>
                      <Select
                        label="Strictness"
                        value={adminDraft.strictness_level}
                        onChange={(e) => setDraft('strictness_level', e.target.value)}
                      >
                        {Object.entries(STRICTNESS_LABELS).map(([value, label]) => (
                          <MenuItem key={value} value={value}>{label}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={12} sm={6}>
                    <FormControl fullWidth>
                      <InputLabel>Highest Rating Allowed</InputLabel>
                      <Select
                        label="Highest Rating Allowed"
                        value={adminDraft.max_rating}
                        onChange={(e) => setDraft('max_rating', e.target.value)}
                      >
                        <MenuItem value="">No extra limit</MenuItem>
                        {Object.entries(RATING_LABELS).map(([value, label]) => (
                          <MenuItem key={value} value={value}>{label}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={12}>
                    <Autocomplete
                      multiple
                      freeSolo
                      options={profile.allowed_topics || []}
                      value={adminDraft.blocked_categories}
                      onChange={(event, value) => setDraft('blocked_categories', value.map((v) => v.trim()).filter(Boolean))}
                      getOptionLabel={formatTopic}
                      renderTags={(value, getTagProps) =>
                        value.map((topic, index) => (
                          <Chip label={formatTopic(topic)} size="small" color="warning" {...getTagProps({ index })} key={topic} />
                        ))
                      }
                      renderInput={(params) => (
                        <TextField {...params} label="Blocked Topics" placeholder="Add a topic to block" helperText="A word blocks every topic containing it, e.g. gaming blocks gaming family" />
                      )}
                    />
                  </Grid>
                  <Grid item xs={12}>
                    <Autocomplete
                      multiple
                      options={SENSITIVE_TOPICS}
                      value={adminDraft.allowed_sensitive_topics}
                      onChange={(event, value) => setDraft('allowed_sensitive_topics', value)}
                      getOptionLabel={formatTopic}
                      renderTags={(value, getTagProps) =>
                        value.map((topic, index) => (
                          <Chip label={formatTopic(topic)} size="small" {...getTagProps({ index })} key={topic} />
                        ))
                      }
                      renderInput={(params) => (
                        <TextField {...params} label="Sensitive Topics Allowed (Teens)" helperText="Lets a teen see teen-rated content on these topics. Has no effect for a child." />
                      )}
                    />
                  </Grid>
                </Grid>
                <Button
                  variant="contained"
                  disabled={saving}
                  startIcon={saving ? <CircularProgress size={20} /> : <SaveIcon />}
                  onClick={handleSaveAdmin}
                  sx={{ mt: 2 }}
                >
                  {saving ? 'Saving...' : 'Save Controls'}
                </Button>
              </>
            ) : (
              <>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  Set by an administrator on a parent's request. They cannot be changed here.
                </Typography>
                <Grid container spacing={2}>
                  <Grid item xs={12} sm={4}>
                    <Typography variant="body2" color="text.secondary">
                      Strictness
                    </Typography>
                    <Typography variant="body1" fontWeight="medium" sx={{ textTransform: 'capitalize' }}>
                      {controls?.strictness_level}
                    </Typography>
                  </Grid>
                  <Grid item xs={12} sm={4}>
                    <Typography variant="body2" color="text.secondary">
                      Highest rating allowed
                    </Typography>
                    <Typography variant="body1" fontWeight="medium">
                      {controls?.max_rating ? RATING_LABELS[controls.max_rating] : 'No extra limit'}
                    </Typography>
                  </Grid>
                  <Grid item xs={12} sm={4}>
                    <Typography variant="body2" color="text.secondary">
                      Blocked topics
                    </Typography>
                    {blockedCategories.length === 0 ? (
                      <Typography variant="body1" fontWeight="medium">
                        None
                      </Typography>
                    ) : (
                      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 0.5 }}>
                        {blockedCategories.map((topic) => (
                          <Chip key={topic} label={formatTopic(topic)} size="small" color="warning" variant="outlined" />
                        ))}
                      </Box>
                    )}
                  </Grid>
                </Grid>
              </>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
};

export default ViewerProfile;
