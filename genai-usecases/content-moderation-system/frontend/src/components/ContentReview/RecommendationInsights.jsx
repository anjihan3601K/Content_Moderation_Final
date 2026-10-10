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
  List,
  ListItem,
  ListItemText,
  TextField,
  Typography,
} from '@mui/material';
import {
  CheckCircle,
  Block,
  Save as SaveIcon,
} from '@mui/icons-material';
import { recommendationAPI } from '../../services/api';

const RATING_LABELS = {
  all_ages: { label: 'All ages', color: 'success' },
  teen: { label: 'Teen (13+)', color: 'info' },
  adult: { label: 'Adult (18+)', color: 'warning' },
  blocked: { label: 'Blocked', color: 'error' },
};

const TIER_LABELS = { child: 'Children', teen: 'Teens', adult: 'Adults' };

// Why the safety gate withholds an item from an age group
const REASON_LABELS = {
  blocked: 'Blocked or removed',
  not_servable_status: 'Not approved yet',
  pending_review: 'Not approved yet',
  unrated: 'Not rated yet',
  above_tier: 'Rated above this age group',
  escalation: 'High-risk category',
  unlisted_topic: 'Topic not on the list for this age group',
  policy_violation: 'Has a policy violation',
  toxicity: 'Toxicity too high for this age group',
  sensitive_topic: 'Sensitive topic, needs parental allowance',
  borderline: 'Borderline content',
  high_uncertainty: 'Agents were not confident enough',
  missing_signals: 'Confidence signals missing',
  parental_block: 'Blocked by parental controls',
  invalid: 'Record could not be read',
};

// Audience tags set the youngest group a post may reach; they are not topics
const AUDIENCE_LABELS = { child: 'Child', teen: 'Teen', '18_plus': '18+' };

const formatLabel = (value) => AUDIENCE_LABELS[value] || String(value).replace(/_/g, ' ');

const percent = (value) => (value === null || value === undefined ? 'n/a' : `${Math.round(value * 100)}%`);

const RecommendationInsights = ({ contentId, refreshKey }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState(null);
  const [tagDraft, setTagDraft] = useState([]);
  const [savingTags, setSavingTags] = useState(false);
  const [tagError, setTagError] = useState(null);
  const [tagSuccess, setTagSuccess] = useState(null);

  const applyData = (result) => {
    setData(result);
    setTagDraft([...new Set([...(result.audience_tags || []), result.category, ...(result.content_topics || [])].filter((tag) => tag && tag !== 'unknown'))]);
  };

  const handleSaveTags = async () => {
    setSavingTags(true);
    setTagError(null);
    setTagSuccess(null);
    try {
      const updated = await recommendationAPI.updateItemTags(contentId, tagDraft);
      // The tags response carries no precedents; keep the ones already shown.
      applyData({ ...updated, precedents: data?.precedents || [] });
      setTagSuccess('Tags saved');
    } catch (err) {
      console.error('Error saving tags:', err);
      const detail = err.response?.data?.detail;
      setTagError(typeof detail === 'string' ? detail : 'Tags must be 1 to 10 short plain-text labels');
    } finally {
      setSavingTags(false);
    }
  };

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setMessage(null);
      try {
        applyData(await recommendationAPI.getItemRecommendation(contentId));
      } catch (err) {
        setData(null);
        const status = err.response?.status;
        if (status === 404) {
          setMessage('No recommendation data for this content yet. It appears after AI moderation runs with recommendations enabled, or after a manual review.');
        } else if (status === 403) {
          setMessage('This content is in a high-risk category. Only senior moderators can see its recommendation details.');
        } else {
          console.error('Error loading recommendation insights:', err);
          setMessage('Recommendation details could not be loaded.');
        }
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [contentId, refreshKey]);

  const rating = data ? RATING_LABELS[data.audience_rating] || { label: 'Not rated', color: 'default' } : null;

  return (
    <Card sx={{ mt: 2 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Recommendation
        </Typography>

        {loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
            <CircularProgress size={28} />
          </Box>
        )}

        {!loading && message && <Alert severity="info">{message}</Alert>}

        {!loading && data && (
          <>
            {/* Audience rating */}
            <Typography variant="body2" color="text.secondary">
              Audience rating
            </Typography>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 0.5, mb: 2 }}>
              <Chip label={rating.label} color={rating.color} size="small" />
              {data.is_escalated && <Chip label="High-risk category" color="error" size="small" variant="outlined" />}
              {data.human_reviewed && <Chip label="Human reviewed" size="small" variant="outlined" />}
            </Box>

            {/* Tags (editable) */}
            <Typography variant="body2" color="text.secondary">
              Tags ({data.tags_source === 'moderator' ? 'set by a moderator' : 'generated by AI moderation'})
            </Typography>
            <Autocomplete
              multiple
              freeSolo
              size="small"
              options={[...(data.audience_tag_options || []), ...(data.known_topics || []), 'others']}
              value={tagDraft}
              onChange={(event, value) => {
                setTagDraft([...new Set(value.map((tag) => tag.trim().toLowerCase().replace(/\+/g, '_plus').replace(/[\s-]+/g, '_')).filter(Boolean))]);
                setTagSuccess(null);
              }}
              getOptionLabel={formatLabel}
              renderTags={(value, getTagProps) =>
                value.map((tag, index) => (
                  <Chip label={formatLabel(tag)} size="small" {...getTagProps({ index })} key={tag} />
                ))
              }
              renderInput={(params) => <TextField {...params} placeholder="Add a tag" helperText="Pick from the list or type your own and press Enter. The first topic is the category. Child, Teen and 18+ set the youngest group and can only make the rating stricter." />}
              sx={{ mt: 0.5 }}
            />
            {tagError && <Alert severity="error" sx={{ mt: 1 }} onClose={() => setTagError(null)}>{tagError}</Alert>}
            {tagSuccess && <Alert severity="success" sx={{ mt: 1 }} onClose={() => setTagSuccess(null)}>{tagSuccess}</Alert>}
            <Button
              size="small"
              variant="outlined"
              startIcon={savingTags ? <CircularProgress size={16} /> : <SaveIcon />}
              disabled={savingTags || tagDraft.length === 0}
              onClick={handleSaveTags}
              sx={{ mt: 1, mb: 2 }}
            >
              {savingTags ? 'Saving...' : 'Save Tags'}
            </Button>

            {/* Suggested for */}
            <Typography variant="body2" color="text.secondary">
              Suggested for
            </Typography>
            <List dense disablePadding sx={{ mb: 1 }}>
              {(data.suitable_for || []).map((entry) => (
                <ListItem key={entry.age_tier} disableGutters sx={{ py: 0 }}>
                  {entry.served ? (
                    <CheckCircle color="success" fontSize="small" sx={{ mr: 1 }} />
                  ) : (
                    <Block color="disabled" fontSize="small" sx={{ mr: 1 }} />
                  )}
                  <ListItemText
                    primary={TIER_LABELS[entry.age_tier]}
                    secondary={entry.served ? 'Can appear in their feed' : REASON_LABELS[entry.reason] || formatLabel(entry.reason)}
                  />
                </ListItem>
              ))}
            </List>

            <Divider sx={{ my: 1.5 }} />

            {/* Signals */}
            <Typography variant="body2" color="text.secondary">
              Agent agreement
            </Typography>
            <Typography variant="body2" sx={{ mb: 1.5 }}>
              Disagreement {percent(data.agent_disagreement)}, lowest confidence {percent(data.overall_confidence)}
            </Typography>

            {/* Suggested moderator action */}
            <Typography variant="body2" color="text.secondary">
              Suggested moderator action
            </Typography>
            <Typography variant="body2" sx={{ mb: 1.5, textTransform: 'capitalize' }}>
              {data.suggested_action} ({percent(data.confidence)},{' '}
              {data.suggestion_source === 'precedents' ? 'from similar past cases' : 'from the agents\' signals'})
            </Typography>

            {/* Similar past cases */}
            <Typography variant="body2" color="text.secondary">
              Similar past cases
            </Typography>
            {(data.precedents || []).length === 0 ? (
              <Typography variant="body2">None yet</Typography>
            ) : (
              <List dense disablePadding>
                {data.precedents.map((precedent) => (
                  <ListItem key={precedent.case_id} disableGutters sx={{ py: 0 }}>
                    <ListItemText
                      primary={`${formatLabel(precedent.category)}: moderator chose ${precedent.final_human_action}`}
                      secondary={`Agents said ${precedent.agent_verdict}, similarity ${percent(precedent.similarity_score)}`}
                    />
                  </ListItem>
                ))}
              </List>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
};

export default RecommendationInsights;
