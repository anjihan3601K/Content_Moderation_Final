import React, { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardActions,
  CardContent,
  Chip,
  CircularProgress,
  Container,
  Grid,
  Typography,
} from '@mui/material';
import {
  Refresh as RefreshIcon,
  ThumbUp,
  ThumbDown,
} from '@mui/icons-material';
import { useAuthStore } from '../../store/authStore';
import { recommendationAPI } from '../../services/api';
import ViewerProfile from '../Settings/ViewerProfile';

const TIER_LABELS = { child: 'Child', teen: 'Teen', adult: 'Adult' };

const RATING_LABELS = {
  all_ages: { label: 'All ages', color: 'success' },
  teen: { label: 'Teen (13+)', color: 'info' },
  adult: { label: 'Adult (18+)', color: 'warning' },
};

const formatLabel = (value) => String(value).replace(/_/g, ' ');

const tagsOf = (item) => [...new Set([item.content_category, ...(item.content_topics || [])].filter(Boolean))];

const ForYou = () => {
  const { user } = useAuthStore();
  const [feed, setFeed] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);
  const [error, setError] = useState(null);
  const [reactions, setReactions] = useState({});

  const loadFeed = async () => {
    setLoading(true);
    setError(null);
    try {
      const [feedData, profileData] = await Promise.all([
        recommendationAPI.getFeed(10),
        recommendationAPI.getPreferences(user.user_id),
      ]);
      setFeed(feedData);
      setProfile(profileData);
      setReactions({});
    } catch (err) {
      console.error('Error loading recommendations:', err);
      if (err.response?.status === 404) {
        setUnavailable(true);
      } else {
        setError(err.response?.data?.detail || 'Failed to load recommendations');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (user?.user_id) loadFeed();
  }, [user?.user_id]);

  const handleReaction = async (item, eventType) => {
    setReactions({ ...reactions, [item.item_id]: eventType });
    try {
      await recommendationAPI.sendFeedback({ event_type: eventType, item_id: item.item_id });
    } catch (err) {
      console.error('Error sending feedback:', err);
      setError(err.response?.data?.detail || 'Failed to record your feedback');
    }
  };

  if (unavailable) {
    return (
      <Container maxWidth="md" sx={{ py: 4 }}>
        <Alert severity="info">Personalized recommendations are not enabled on this server.</Alert>
      </Container>
    );
  }

  const needsSetup = profile && (!profile.tier_declared || (profile.explicit_interests || []).length === 0);
  const withheld = feed ? feed.rejected_count : 0;

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box>
          <Typography variant="h4" component="h1" fontWeight="bold" gutterBottom>
            For You
          </Typography>
          <Typography variant="body1" color="text.secondary">
            Posts picked for your age group and interests
          </Typography>
        </Box>
        <Button variant="outlined" startIcon={<RefreshIcon />} onClick={loadFeed} disabled={loading}>
          Refresh
        </Button>
      </Box>

      {error && (
        <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      {needsSetup && (
        <Alert severity="info" sx={{ mb: 3 }}>
          {!profile.tier_declared
            ? 'Add your date of birth and pick some interests in the profile card to get better recommendations.'
            : 'Pick some interests in the profile card to get better recommendations.'}
        </Alert>
      )}

      <Grid container spacing={3}>
        {/* Feed */}
        <Grid item xs={12} md={7}>
          {loading && (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
              <CircularProgress />
            </Box>
          )}

          {!loading && feed && (
            <>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                Showing {feed.items.length} of {feed.passed_gate_count} posts available to the {TIER_LABELS[feed.age_tier]} age group
                {withheld > 0 && `; ${withheld} not shown`}
              </Typography>

              {feed.items.length === 0 && (
                <Alert severity="info">
                  Nothing to recommend yet. Posts appear here once they have been moderated and approved.
                </Alert>
              )}

              {feed.items.map((item) => {
                const rating = RATING_LABELS[item.audience_rating];
                const reaction = reactions[item.item_id];
                return (
                  <Card key={item.item_id} sx={{ mb: 2 }}>
                    <CardContent sx={{ pb: 1 }}>
                      <Typography variant="body1" sx={{ mb: 1.5, whiteSpace: 'pre-wrap' }}>
                        {item.content_text || 'No text'}
                      </Typography>
                      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                        {rating && <Chip label={rating.label} color={rating.color} size="small" />}
                        {tagsOf(item).map((tag) => (
                          <Chip key={tag} label={formatLabel(tag)} size="small" variant="outlined" />
                        ))}
                      </Box>
                    </CardContent>
                    <CardActions>
                      <Button
                        size="small"
                        startIcon={<ThumbUp />}
                        color={reaction === 'view_long' ? 'success' : 'inherit'}
                        disabled={Boolean(reaction)}
                        onClick={() => handleReaction(item, 'view_long')}
                      >
                        Interested
                      </Button>
                      <Button
                        size="small"
                        startIcon={<ThumbDown />}
                        color={reaction === 'skip' ? 'error' : 'inherit'}
                        disabled={Boolean(reaction)}
                        onClick={() => handleReaction(item, 'skip')}
                      >
                        Not for me
                      </Button>
                    </CardActions>
                  </Card>
                );
              })}
            </>
          )}
        </Grid>

        {/* Profile */}
        <Grid item xs={12} md={5}>
          <ViewerProfile onSaved={loadFeed} />
        </Grid>
      </Grid>
    </Container>
  );
};

export default ForYou;
