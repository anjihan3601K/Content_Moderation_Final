import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Container,
  Typography,
  Button,
  TextField,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Tab,
  Tabs,
  Paper,
  Divider,
  Alert,
  Snackbar,
  CircularProgress,
  Grid,
  IconButton
} from '@mui/material';
import {
  Add as AddIcon,
  Star as StarIcon,
  LocalFireDepartment as HotIcon,
  NewReleases as NewIcon,
  ThumbUp as ThumbUpIcon,
  Image as ImageIcon,
  Videocam as VideocamIcon,
  CloudUpload as CloudUploadIcon,
  Delete as DeleteIcon
} from '@mui/icons-material';
import { useAuthStore } from '../../store/authStore';
import { storiesAPI } from '../../services/api';

// Import custom hooks
import {
  useStories,
  useUserStories,
  useStoryStats,
  useFeaturedStories,
  useStoriesFilter
} from '../../hooks/useStories';

// Import widgets
import StatsWidget from '../widgets/StatsWidget';
import FeaturedStoriesWidget from '../widgets/FeaturedStoriesWidget';
import StoriesGrid from '../widgets/StoriesGrid';
import CommunityGuidelinesWidget from '../widgets/CommunityGuidelinesWidget';
import ModerationProcessWidget from '../widgets/ModerationProcessWidget';
import UserStatsWidget from '../widgets/UserStatsWidget';

const CommunityDashboard = () => {
  const navigate = useNavigate();
  const { user } = useAuthStore();

  // State management
  const [tabValue, setTabValue] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');

  // Dialog state
  const [openDialog, setOpenDialog] = useState(false);
  const [newStory, setNewStory] = useState({ title: '', content: '', imageUrl: '', videoUrl: '', attachedImage: null });
  const [submitting, setSubmitting] = useState(false);

  // Snackbar state
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' });

  // Use custom hooks for data fetching
  const { stories: allStories, loading, refetch } = useStories({ visibleOnly: true, limit: 100 });
  const { stories: myStories, refetch: refetchMyStories } = useUserStories(user?.user_id, { limit: 50 });

  // Calculate stats and featured stories
  const stats = useStoryStats(allStories);
  const featuredStories = useFeaturedStories(allStories, 3);

  // Determine which stories to display based on tab
  const getCurrentTabStories = () => {
    switch (tabValue) {
      case 0: // All Stories
        return allStories;
      case 1: // Trending
        return allStories;
      case 2: // New
        return allStories;
      case 3: // My Stories
        return myStories;
      default:
        return allStories;
    }
  };

  // Apply filtering with search and sort
  const filteredStories = useStoriesFilter(
    getCurrentTabStories(),
    searchQuery,
    {
      sortBy: tabValue === 1 ? 'trending' : tabValue === 2 ? 'newest' : null
    }
  );

  // Calculate stats with user stories count
  const dashboardStats = {
    totalStories: stats.totalStories,
    totalViews: stats.totalViews,
    totalComments: stats.totalComments,
    myStories: myStories.length
  };

  // Calculate user stats
  const userStats = {
    totalStories: myStories.length,
    published: myStories.filter(s => s.moderation_status?.toLowerCase() === 'approved' && s.is_visible).length,
    underReview: myStories.filter(s => ['pending', 'flagged', 'pending_human_review'].includes(s.moderation_status?.toLowerCase())).length,
    totalViews: myStories.reduce((sum, s) => sum + (s.view_count || 0), 0)
  };

  const handleOpenDialog = () => setOpenDialog(true);

  const handleCloseDialog = () => {
    setOpenDialog(false);
    setNewStory({ title: '', content: '', imageUrl: '', videoUrl: '', attachedImage: null });
  };

  const handleImageUpload = (event) => {
    const file = event.target.files[0];
    if (file) {
      if (file.size > 5 * 1024 * 1024) {
        showSnackbar('Image file size must be less than 5MB', 'error');
        return;
      }
      const reader = new FileReader();
      reader.onloadend = () => {
        setNewStory(prev => ({ ...prev, attachedImage: reader.result }));
      };
      reader.readAsDataURL(file);
    }
  };

  const handleSubmitStory = async () => {
    if (!newStory.title.trim() || !newStory.content.trim()) {
      showSnackbar('Please fill in all fields', 'error');
      return;
    }

    try {
      setSubmitting(true);
      
      let finalContent = newStory.content.trim();
      if (newStory.imageUrl.trim()) {
        finalContent += `\n\n![Image](${newStory.imageUrl.trim()})`;
      }
      if (newStory.videoUrl.trim()) {
        finalContent += `\n\n[Video](${newStory.videoUrl.trim()})`;
      }
      if (newStory.attachedImage) {
        finalContent += `\n\n![Attached Image](${newStory.attachedImage})`;
      }

      const payload = {
        title: String(newStory.title || ''),
        content_text: finalContent,
        image_urls: newStory.imageUrl.trim() ? [newStory.imageUrl.trim()] : [],
        video_urls: newStory.videoUrl.trim() ? [newStory.videoUrl.trim()] : []
      };

      // Only add user fields if they exist and are valid strings
      if (user?.user_id) {
        payload.user_id = String(user.user_id);
      }
      if (user?.username || user?.full_name) {
        payload.username = String(user.username || user.full_name || '');
      }

      console.log('Submitting story payload:', payload);
      const response = await storiesAPI.submitStory(payload);

      if (response?.success) {
        showSnackbar(
          response.is_approved
            ? 'Story published successfully!'
            : 'Story submitted for review',
          'success'
        );
        handleCloseDialog();

        // Switch to appropriate tab
        if (response.is_approved) {
          setTabValue(0); // Switch to "All Stories" for approved stories
        } else {
          setTabValue(3); // Switch to "My Stories" for pending/flagged stories
        }

        // Refetch both story lists after a short delay
        setTimeout(() => {
          refetch(); // Refetch all visible stories
          refetchMyStories(); // Refetch user's stories (includes pending)
        }, 500);
      }
    } catch (error) {
      console.error('Error submitting story:', error);
      const errorDetail = error.response?.data?.detail;
      let errorMessage = 'Failed to submit story';

      if (typeof errorDetail === 'string') {
        errorMessage = errorDetail;
      } else if (Array.isArray(errorDetail)) {
        // Pydantic validation errors are arrays
        errorMessage = errorDetail.map(err => err.msg || JSON.stringify(err)).join(', ');
      } else if (errorDetail && typeof errorDetail === 'object') {
        errorMessage = JSON.stringify(errorDetail);
      }

      showSnackbar(errorMessage, 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleStoryClick = (storyId) => {
    navigate(`/stories/${storyId}`);
  };

  const handleTabChange = (event, newValue) => {
    setTabValue(newValue);
  };

  const showSnackbar = (message, severity = 'success') => {
    setSnackbar({ open: true, message, severity });
  };

  const handleCloseSnackbar = () => {
    setSnackbar({ ...snackbar, open: false });
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Container maxWidth="xl" sx={{ py: 4 }}>
      <Grid container spacing={3}>
        {/* Main Content - Left Side */}
        <Grid item xs={12} lg={8}>
          {/* Header Section */}
          <Box sx={{ mb: 4 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
              <Box>
                <Typography variant="h4" component="h1" fontWeight="bold" gutterBottom>
                  Community Stories
                </Typography>
                <Typography variant="body1" color="text.secondary">
                  Share your experiences and connect with the community
                </Typography>
              </Box>
              <Button
                variant="contained"
                size="large"
                startIcon={<AddIcon />}
                onClick={handleOpenDialog}
                sx={{
                  borderRadius: 2,
                  px: 3,
                  py: 1.5,
                  textTransform: 'none',
                  fontSize: '1rem'
                }}
              >
                Share Your Story
              </Button>
            </Box>

            {/* Stats Widget */}
            <Box sx={{ mb: 3 }}>
              <StatsWidget stats={dashboardStats} />
            </Box>

        {/* Search Bar - Using Paper directly for simplicity */}
        <Paper elevation={1} sx={{ p: 2, mb: 3 }}>
          <TextField
            fullWidth
            placeholder="Search stories by title, content, or author..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            sx={{ '& .MuiOutlinedInput-root': { '& fieldset': { border: 'none' } } }}
          />
        </Paper>

        {/* Tabs */}
        <Paper elevation={1}>
          <Tabs
            value={tabValue}
            onChange={handleTabChange}
            variant="fullWidth"
            indicatorColor="primary"
            textColor="primary"
          >
            <Tab icon={<StarIcon />} label="All Stories" iconPosition="start" />
            <Tab icon={<HotIcon />} label="Trending" iconPosition="start" />
            <Tab icon={<NewIcon />} label="New" iconPosition="start" />
            <Tab icon={<ThumbUpIcon />} label="My Stories" iconPosition="start" />
          </Tabs>
        </Paper>
      </Box>

      {/* Featured Stories Widget - Only show on "All Stories" tab */}
      {tabValue === 0 && featuredStories.length > 0 && (
        <>
          <FeaturedStoriesWidget stories={featuredStories} onStoryClick={handleStoryClick} />
          <Divider sx={{ my: 4 }} />
        </>
      )}

      {/* Stories Grid Section */}
      <Box>
        <Typography variant="h5" fontWeight="bold" gutterBottom>
          {tabValue === 0 && 'All Stories'}
          {tabValue === 1 && 'Trending Stories'}
          {tabValue === 2 && 'New Stories'}
          {tabValue === 3 && 'My Stories'}
        </Typography>

        <StoriesGrid
          stories={filteredStories}
          onStoryClick={handleStoryClick}
          showStatus={tabValue === 3}
          emptyMessage={
            searchQuery
              ? 'No stories found matching your search'
              : tabValue === 3
              ? 'You haven\'t shared any stories yet'
              : 'No stories available'
          }
        />

            {/* Show "Share Story" button in empty state for My Stories tab */}
            {filteredStories.length === 0 && tabValue === 3 && !searchQuery && (
              <Box sx={{ textAlign: 'center', mt: 3 }}>
                <Button variant="contained" startIcon={<AddIcon />} onClick={handleOpenDialog}>
                  Share Your First Story
                </Button>
              </Box>
            )}
          </Box>
        </Grid>

        {/* Sidebar - Right Side */}
        <Grid item xs={12} lg={4}>
          <Box sx={{ position: { lg: 'sticky' }, top: { lg: 100 } }}>
            {/* User Stats Widget */}
            <Box sx={{ mb: 3 }}>
              <UserStatsWidget stats={userStats} />
            </Box>

            {/* Community Guidelines Widget */}
            <Box sx={{ mb: 3 }}>
              <CommunityGuidelinesWidget />
            </Box>

            {/* Moderation Process Widget */}
            <Box>
              <ModerationProcessWidget />
            </Box>
          </Box>
        </Grid>
      </Grid>

      {/* Create Story Dialog */}
      <Dialog open={openDialog} onClose={handleCloseDialog} maxWidth="md" fullWidth>
        <DialogTitle>
          Share Your Story
        </DialogTitle>
        <DialogContent dividers>
          <TextField
            autoFocus
            fullWidth
            label="Story Title"
            placeholder="Give your story a catchy title..."
            value={newStory.title}
            onChange={(e) => setNewStory({ ...newStory, title: e.target.value })}
            sx={{ mb: 3 }}
            inputProps={{ maxLength: 200 }}
            helperText={`${newStory.title.length}/200 characters`}
          />
          <TextField
            fullWidth
            multiline
            rows={8}
            label="Your Story"
            placeholder="Share your experience, thoughts, or insights with the community..."
            value={newStory.content}
            onChange={(e) => setNewStory({ ...newStory, content: e.target.value })}
            inputProps={{ maxLength: 5000 }}
            helperText={`${newStory.content.length}/5000 characters`}
            sx={{ mb: 3 }}
          />

          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1, fontWeight: 600 }}>
            Attach Media & URLs (Optional)
          </Typography>
          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                size="small"
                label="Image URL"
                placeholder="https://example.com/image.jpg"
                value={newStory.imageUrl}
                onChange={(e) => setNewStory({ ...newStory, imageUrl: e.target.value })}
                InputProps={{
                  startAdornment: <ImageIcon sx={{ color: 'action.active', mr: 1 }} />,
                }}
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                size="small"
                label="Video URL"
                placeholder="https://youtube.com/watch?v=..."
                value={newStory.videoUrl}
                onChange={(e) => setNewStory({ ...newStory, videoUrl: e.target.value })}
                InputProps={{
                  startAdornment: <VideocamIcon sx={{ color: 'action.active', mr: 1 }} />,
                }}
              />
            </Grid>
          </Grid>

          <Box sx={{ mb: 2 }}>
            <Button
              variant="outlined"
              component="label"
              startIcon={<CloudUploadIcon />}
              size="small"
            >
              Upload Image File
              <input
                type="file"
                hidden
                accept="image/*"
                onChange={handleImageUpload}
              />
            </Button>
            {newStory.attachedImage && (
              <Box sx={{ mt: 1, display: 'flex', alignItems: 'center', gap: 2 }}>
                <Box
                  component="img"
                  src={newStory.attachedImage}
                  alt="Attached preview"
                  sx={{ width: 100, height: 70, objectFit: 'cover', borderRadius: 1, border: '1px solid #ccc' }}
                />
                <IconButton
                  color="error"
                  size="small"
                  onClick={() => setNewStory(prev => ({ ...prev, attachedImage: null }))}
                >
                  <DeleteIcon />
                </IconButton>
              </Box>
            )}
          </Box>

          <Alert severity="info" sx={{ mt: 2 }}>
            Your story will be reviewed by our AI moderation system. Stories that follow community guidelines will be published immediately.
          </Alert>
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button onClick={handleCloseDialog} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={handleSubmitStory}
            disabled={submitting || !newStory.title.trim() || !newStory.content.trim()}
            startIcon={submitting ? <CircularProgress size={20} /> : <AddIcon />}
          >
            {submitting ? 'Publishing...' : 'Publish Story'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Snackbar for notifications */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={handleCloseSnackbar}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert onClose={handleCloseSnackbar} severity={snackbar.severity} sx={{ width: '100%' }}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Container>
  );
};

export default CommunityDashboard;
